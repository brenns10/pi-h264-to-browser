import tornado.web, tornado.ioloop, tornado.websocket  
from picamera import PiCamera, PiVideoFrameType, Color
from string import Template
import io, os, socket
from datetime import timedelta

# start configuration
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

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.connect(('8.8.8.8', 0))
serverIp = s.getsockname()[0]

abspath = os.path.abspath(__file__)
dname = os.path.dirname(abspath)
os.chdir(dname)

def getFile(filePath):
    file = open(filePath,'r')
    content = file.read()
    file.close()
    return content

def templatize(content, replacements):
    tmpl = Template(content)
    return tmpl.substitute(replacements)

indexHtml = templatize(getFile('index.html'), {'ip':serverIp, 'port':serverPort, 'fps':camera.framerate})
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

requestHandlers = [
    (r"/ws/", wsHandler),
    (r"/", indexHandler),
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


try:
    streamBuffer = StreamBuffer(camera)
    camera.start_recording(streamBuffer, **recordingOptions) 
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
    loop.start()
except KeyboardInterrupt:
    camera.stop_recording()
    camera.close()
    loop.stop()
