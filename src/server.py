import tornado.ioloop
import tornado.web
import tornado.websocket
from picamera import PiCamera
from picamera import PiVideoFrameType
from picamera import Color

import io
import json
import os
import math
import socket
import sys
import time
from datetime import timedelta
from string import Template


# start configuration
debug = False
if os.getenv("DEBUG_CAM"):
    debug = True
serverPort = 8000

camera = PiCamera(
    sensor_mode=2,
    resolution='1920x1080',
    framerate=30,
)
camera.video_denoise = False
camera.rotation = 180
#camera.exposure_mode = 'night'

recordingOptions = {
    'format' : 'h264', 
    'quality' : 20, 
    'profile' : 'high', 
    'level' : '4.2', 
    'intra_period' : 15, 
    'intra_refresh' : 'both', 
    'inline_headers' : True, 
    'sps_timing' : True,
}

focusPeakingColor = '1.0, 0.0, 0.0, 1.0'
focusPeakingthreshold = 0.055

centerColor = '255, 0, 0, 1.0'
centerThickness = 2

gridColor = '255, 0, 0, 1.0'
gridThickness = 2
# end configuration

while True:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 0))
        serverIp = s.getsockname()[0]
    except OSError as e:
        if e.errno == 101:
            print("Waiting for network to come up...")
            time.sleep(1)
        else:
            raise
    else:
        break
    finally:
        s.close()

abspath = os.path.abspath(__file__)
dname = os.path.dirname(abspath)
os.chdir(dname)

def getFile(filePath):
    file = open(filePath,'r')
    content = file.read()
    file.close()
    return content

def templatize(content, replacements, literal=False):
    if not literal:
        tmpl = Template(content)
        return tmpl.substitute(replacements)
    for key, value in replacements.items():
        content = content.replace(key, str(value))
    return content

indexHtml = templatize(getFile('index.html'), {'REPLACE_IP':serverIp, 'REPLACE_PORT':serverPort, 'REPLACE_FPS':camera.framerate}, True)
centerHtml = templatize(getFile('center.html'), {'ip':serverIp, 'port':serverPort, 'fps':camera.framerate,'color':centerColor, 'thickness':centerThickness})
gridHtml = templatize(getFile('grid.html'), {'ip':serverIp, 'port':serverPort, 'fps':camera.framerate,'color':gridColor, 'thickness':gridThickness})
focusHtml = templatize(getFile('focus.html'), {'ip':serverIp, 'port':serverPort, 'fps':camera.framerate, 'color':focusPeakingColor, 'threshold':focusPeakingthreshold})
jmuxerJs = getFile('jmuxer.min.js')

class StreamBuffer(object):
    def __init__(self,camera):
        self.frameTypes = PiVideoFrameType()
        self.loop = None
        self.buffer = io.BytesIO()
        self.camera = camera

    def setLoop(self, loop):
        self.loop = loop

    def write(self, buf):
        if self.camera.frame.complete and self.camera.frame.frame_type != self.frameTypes.sps_header:
            self.buffer.write(buf)
            if self.loop is not None and wsHandler.hasConnections():
                self.loop.add_callback(callback=wsHandler.broadcast, message=self.buffer.getvalue())
            self.buffer.seek(0)
            self.buffer.truncate()
        else:
            self.buffer.write(buf)

class wsHandler(tornado.websocket.WebSocketHandler):
    connections = []

    def open(self):
        self.connections.append(self)

    def on_close(self):
        self.connections.remove(self)

    def on_message(self, message):
        pass

    @classmethod
    def hasConnections(cl):
        if len(cl.connections) == 0:
            return False
        return True

    @classmethod
    async def broadcast(cl, message):
        for connection in cl.connections:
            try:
                await connection.write_message(message, True)
            except tornado.websocket.WebSocketClosedError:
                pass
            except tornado.iostream.StreamClosedError:
                pass

    def check_origin(self, origin):
        return True

class indexHandler(tornado.web.RequestHandler):
    def get(self):
        self.write(indexHtml)

class centerHandler(tornado.web.RequestHandler):
    def get(self):
        self.write(centerHtml)

class gridHandler(tornado.web.RequestHandler):
    def get(self):
        self.write(gridHtml)

class focusHandler(tornado.web.RequestHandler):
    def get(self):
        self.write(focusHtml)

class jmuxerHandler(tornado.web.RequestHandler):
    def get(self):
        self.set_header('Content-Type', 'text/javascript')
        self.write(jmuxerJs)

# (sz, incr): size of frame and increment
# 0-index is the zoom_level zl
zoom_levels = [
    (1.0, 1.0),
    (0.8, 0.1),
    (0.6, 0.1),
    (0.4, 0.1),
    (0.2, 0.1),
]

# (index into array, x position, y position)
current_zoom = 0, 0, 0


def get_zoom():
    return current_zoom


def set_zoom(zl, x, y):
    global current_zoom
    zl = min(zl, len(zoom_levels) - 1)
    zl = max(zl, 0)
    sz, incr = zoom_levels[zl]
    maxv = round((1 - sz) / incr)
    x = min(int(x), maxv)
    x = max(x, 0)
    y = min(int(y), maxv)
    y = max(y, 0)
    camera.zoom = (x * incr, y * incr, sz, sz)
    current_zoom = zl, x, y


class cameraSettings(tornado.web.RequestHandler):
    def get(self):
        self.set_header("Content-Type", "application/json")
        settings = {
            "awb_mode": camera.awb_mode,
            "awb_mode_choices":  list(PiCamera.AWB_MODES.keys()),
            "brightness": camera.brightness,
            "brightness_range": [0, 100],
            "contrast": camera.contrast,
            "contrast_range": [-100, 100],
            "exposure_compensation": camera.exposure_compensation,
            "exposure_compensation_range": [-25, 25],
            "exposure_mode": camera.exposure_mode,
            "exposure_mode_choices": list(PiCamera.EXPOSURE_MODES.keys()),
            "image_effect": camera.image_effect,
            "image_effect_choices": list(PiCamera.IMAGE_EFFECTS.keys()),
            "iso": camera.iso,
            "iso_range": [100, 800],
            "saturation": camera.saturation,
            "saturation_range": [-100, 100],
            "sharpness": camera.sharpness,
            "sharpness_range": [-100, 100],
            "zoom_level": get_zoom(),
        }
        self.write(json.dumps(settings).encode("utf-8"))

    def _set(self, body, field, min_=None, max_=None, opts=[]):
        new = body.get(field)
        old = getattr(camera, field)
        if (new is None) or (new == old) or \
           (min_ and new < min_) or (max_ and new > max_) or \
           (opts and new not in opts):
            return
        print("CAMERA: {}: {} -> {}".format(field, old, new))
        setattr(camera, field, new)
        res = getattr(camera, field)
        if res != new:
            print(" (rejected, now {})".format(res))

    def post(self):
        body = json.loads(self.request.body.decode("utf-8"))
        self._set(body, "awb_mode", opts=PiCamera.AWB_MODES)
        self._set(body, "brightness", 0, 100)
        self._set(body, "contrast", -100, 100)
        self._set(body, "exposure_compensation", -25, 25)
        self._set(body, "exposure_mode", opts=PiCamera.EXPOSURE_MODES)
        self._set(body, "image_effect", opts=PiCamera.IMAGE_EFFECTS)
        self._set(body, "iso", 0, 1600)
        self._set(body, "saturation", -100, 100)
        self._set(body, "sharpness", -100, 100)
        if "zoom_level" in body:
            val = body["zoom_level"]
            if isinstance(val, list) and len(val) == 3:
                set_zoom(*val)
        self.get()


requestHandlers = [
    (r"/ws/", wsHandler),
    (r"/", indexHandler),
    (r"/cam/", cameraSettings),
    (r"/center/", centerHandler),
    (r"/grid/", gridHandler),
    (r"/focus/", focusHandler),
    (r"/jmuxer.min.js", jmuxerHandler)
]

def update_mem():
    with open("/proc/self/statm") as f:
        statm = f.read()
    with open("/proc/meminfo") as f:
        meminfo_data = f.read()
    vmrss = int(statm.strip().split()[1])
    meminfo = {}
    for line in meminfo_data.strip().split("\n"):
        tup = line.split()
        meminfo[tup[0][:-1]] = int(tup[1])
    viewers = len(wsHandler.connections)
    line = 'Viewers: {} | Me: {:.1f}M | Sys: {:.1f}M / {:.1f}M'.format(
        viewers,
        vmrss / 1024.,
        meminfo["MemAvailable"] / 1024.,
        meminfo["MemTotal"] / 1024.,
    )
    camera.annotate_text = line
    loop.add_timeout(timedelta(seconds=1), update_mem)


def debug_prompt():
    print("Pi Stream Debug. Enter Python expression followed by Ctrl-D to execute.")


def debug_lol(stdin_, _):
    print("DEBUGGER: ", end="")
    line = stdin_.read()
    print(line)
    print(exec(line))
    debug_prompt()

try:
    streamBuffer = StreamBuffer(camera)
    camera.start_recording(streamBuffer, **recordingOptions) 
    camera.zoom = 0, 0, 1, 1
    application = tornado.web.Application(
        requestHandlers,
        websocket_ping_interval=5,
        websocket_ping_timeout=10,
    )
    application.listen(serverPort)
    loop = tornado.ioloop.IOLoop.current()
    streamBuffer.setLoop(loop)
    camera.annotate_background=Color("black")
    loop.add_timeout(timedelta(seconds=1), update_mem)
    # When running under systemd, this gives an error, I assume stdin can't be
    # read.
    if debug:
        loop.add_handler(sys.stdin, debug_lol, tornado.ioloop.IOLoop.READ)
    debug_prompt()
    loop.start()
except KeyboardInterrupt:
    camera.stop_recording()
    camera.close()
    loop.stop()
