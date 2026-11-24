import asyncio, base64, hashlib, json, os, ssl, struct, sys, urllib.request

OPTS = {}
try:
    with open("/data/options.json") as f:
        OPTS = json.load(f)
except Exception:
    pass

HOST = (OPTS.get("console_host") or os.environ.get("CONSOLE_HOST") or "").strip()
KEY = (OPTS.get("api_key") or os.environ.get("API_KEY") or "").strip()
CAM = (OPTS.get("camera_id") or os.environ.get("CAMERA_ID") or "").strip()
CNAME = (OPTS.get("camera_name") or "").strip()
BASE = os.environ.get("PROTECT_BASE") or "https://%s/proxy/protect/integration/v1/cameras" % HOST
INGRESS_IP = os.environ.get("INGRESS_IP", "172.30.32.2")
PORT = int(os.environ.get("PORT", "8099"))
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
SECRETS = [s for s in (KEY,) if s]

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def log(*a):
    msg = " ".join(str(x) for x in a)
    for s in SECRETS:
        msg = msg.replace(s, "***")
    print(msg, flush=True)


def protect(method, path):
    req = urllib.request.Request(BASE + path, method=method, headers={"X-API-KEY": KEY, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15, context=CTX) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError("Protect answered %s" % e.code)
    except Exception as e:
        raise RuntimeError("Could not reach Protect (%s)" % e.__class__.__name__)
    return json.loads(body) if body else {}


def resolve_camera():
    global CAM
    if CAM:
        return
    cams = protect("GET", "")
    if not isinstance(cams, list):
        raise RuntimeError("Could not read the camera list")
    if CNAME:
        for c in cams:
            if CNAME.lower() in str(c.get("name", "")).lower():
                CAM = c["id"]
                log("Using camera", c.get("name"), CAM)
                return
    log("Cameras found on this console:")
    for c in cams:
        log("  name: %s   id: %s" % (c.get("name"), c.get("id")))
    raise RuntimeError("Set camera_name or camera_id in the add-on configuration")


ENCODERS = {
    "opus": ("libopus", "rtp", ["-application:a", "lowdelay"]),
    "aac": ("aac", "adts", []),
    "vorbis": ("libvorbis", "ogg", []),
}


def frame(opcode, payload=b""):
    n = len(payload)
    if n < 126:
        head = struct.pack("!BB", 0x80 | opcode, n)
    elif n < 65536:
        head = struct.pack("!BBH", 0x80 | opcode, 126, n)
    else:
        head = struct.pack("!BBQ", 0x80 | opcode, 127, n)
    return head + payload


async def read_frame(reader):
    b1, b2 = await reader.readexactly(2)
    fin, op = b1 & 0x80, b1 & 0x0F
    n = b2 & 0x7F
    if n == 126:
        n = struct.unpack("!H", await reader.readexactly(2))[0]
    elif n == 127:
        n = struct.unpack("!Q", await reader.readexactly(8))[0]
    if n > (1 << 20):
        raise ValueError("frame too large")
    mask = await reader.readexactly(4) if b2 & 0x80 else None
    data = await reader.readexactly(n) if n else b""
    if mask:
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(data)) if n < 64 else int.from_bytes(data, "big") ^ int.from_bytes((mask * (n // 4 + 1))[:n], "big")
        if isinstance(data, int):
            data = data.to_bytes(n, "big")
    return fin, op, data


async def send_json(writer, obj):
    writer.write(frame(0x1, json.dumps(obj).encode()))
    await writer.drain()


async def talk(reader, writer):
    proc = None
    url = ""
    total = 0
    try:
        sess = await asyncio.get_running_loop().run_in_executor(None, lambda: (resolve_camera(), protect("POST", "/%s/talkback-session" % CAM))[1])
        url = str(sess.get("url", ""))
        if url:
            SECRETS.append(url)
        codec = str(sess.get("codec", "")).lower().strip()
        rate = int(sess.get("samplingRate") or 0)
        enc = ENCODERS.get(codec)
        if not enc or not rate or not url:
            raise RuntimeError("The doorbell asked for an audio format I can't send (%s)" % codec)
        args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-probesize", "32", "-analyzeduration", "0",
                "-f", "s16le", "-ar", "16000", "-ac", "1", "-i", "pipe:0", "-vn", "-c:a", enc[0], *enc[2],
                "-ar:a", str(rate), "-ac:a", "1", "-flush_packets", "1", "-f", enc[1], url]
        proc = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)

        async def drain():
            while True:
                line = await proc.stderr.readline()
                if not line:
                    return
                log("ffmpeg:", line.decode(errors="replace").strip())

        asyncio.ensure_future(drain())
        log("Talk started with", codec, rate)
        await send_json(writer, {"type": "ready"})
        while True:
            if proc.returncode is not None:
                raise RuntimeError("The audio encoder stopped")
            fin, op, data = await read_frame(reader)
            if op == 0x2:
                total += len(data)
                proc.stdin.write(data)
                await proc.stdin.drain()
            elif op == 0x1:
                if data == b"stop":
                    break
            elif op == 0x9:
                writer.write(frame(0xA, data))
                await writer.drain()
            elif op == 0x8:
                break
    except (asyncio.IncompleteReadError, ConnectionError, BrokenPipeError):
        pass
    except Exception as e:
        log("Talk error:", e)
        try:
            await send_json(writer, {"type": "error", "value": str(e)})
        except Exception:
            pass
    finally:
        if proc and proc.returncode is None:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                proc.kill()
            except Exception:
                pass
        if url and url in SECRETS:
            SECRETS.remove(url)
        log("Talk ended after", total, "bytes of audio")
        try:
            writer.write(frame(0x8))
            await writer.drain()
        except Exception:
            pass


async def handle(reader, writer):
    try:
        peer = writer.get_extra_info("peername")[0]
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
        lines = head.decode("latin1").split("\r\n")
        method, path, _ = lines[0].split(" ", 2)
        hdrs = {}
        for ln in lines[1:]:
            if ":" in ln:
                k, v = ln.split(":", 1)
                hdrs[k.strip().lower()] = v.strip()
        if peer != INGRESS_IP:
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        elif path.split("?")[0].rstrip("/") == "/talk" and hdrs.get("upgrade", "").lower() == "websocket":
            acc = base64.b64encode(hashlib.sha1((hdrs["sec-websocket-key"] + GUID).encode()).digest()).decode()
            writer.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n" % acc).encode())
            await writer.drain()
            await talk(reader, writer)
        else:
            body = b"UniFi talkback relay is running."
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
        await writer.drain()
    except Exception as e:
        log("Request error:", e.__class__.__name__)
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def main():
    if not HOST and "PROTECT_BASE" not in os.environ or not KEY:
        log("Set console_host and api_key in the add-on configuration, then restart.")
        sys.exit(1)
    server = await asyncio.start_server(handle, "0.0.0.0", PORT)
    log("UniFi talkback relay listening on port", PORT)
    async with server:
        await server.serve_forever()


asyncio.run(main())
