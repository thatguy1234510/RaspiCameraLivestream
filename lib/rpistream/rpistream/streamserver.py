import socket
import cv2
import rpistream.camera
import io
import numpy as np
from tempfile import TemporaryFile
import zstandard
import atexit
from rpistream.netutils import *


class Server:
    def __init__(self, **kwargs):
        self.verbose = kwargs.get("verbose", False)
        # output file seems to be corrupted: likely due to output file stream not being closed correctly
        self.Write = kwargs.get("WriteFile", False)
        self.writepath = kwargs.get("path", "")
        self.FileFPS = kwargs.get("fileoutFps", 10)
        self.FileName = kwargs.get("fileName", 'outpy')
        self.iRes = kwargs.get("imageResolution", (640, 480))
        self.out=None
        fourcc = None
        if self.Write:
            try:
                fourcc = cv2.cv.CV_FOURCC(*'MJPG') # OpenCV 2 function
            except:
                fourcc = cv2.VideoWriter_fourcc('M', 'J', 'P', 'G')  # OpenCV 3 function
            
            self.out = cv2.VideoWriter(
                self.writepath+self.FileName+'.avi', fourcc, self.FileFPS, self.iRes)
            
        print("Initilizing socket")
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((kwargs.get("bindto", ""), kwargs.get("port", 8080)))
        s.listen(10)
        self.s = s
        atexit.register(self.close)
        print("Server ready")

    def log(self, m):
        """Prints out if verbose"""
        if self.verbose:
            print(m)  # printout if verbose

    def serve(self):
        """Find client"""
        self.log("Searching for client...")
        while True:
            # wait for client to query the server for a connection
            self.conn, self.clientAddr = self.s.accept()
            self.log('Connected to ' +
                     self.clientAddr[0] + ':' + str(self.clientAddr[1]))
            return None  # only connects to one client

    def serveNoBlock(self):
        """Find client without blocking"""
        self.log("Searching for client...")
        self.s.setblocking(0)
        self.conn, self.clientAddr = self.s.accept() #wait for client to query the server for a connection
        self.log('Connected to ' + self.clientAddr[0] + ':' + str(self.clientAddr[1]))
        return None #only connects to one client 

    def initializeStream(self, img):
        """Sends initial frame of intra-frame compression and preps"""
        self.Sfile = io.BytesIO()
        self.C = zstandard.ZstdCompressor()
        self.prevFrame = img
        np.save(self.Sfile, self.prevFrame)
        send_msg(self.conn, self.C.compress(self.Sfile.getvalue()))
        self.frameno = 0

    def fetchFrame(self, getFrame, args=[]):
        """Fetches a frame given a function"""
        return getFrame(*args)

    def sendFrame(self, img):
        """Sends single frame with intra-frame compression over an initialized stream"""
        if img==None:
            self.close(Exception("sendFrame given null img"))

        # instanciate temporary bytearray to send later
        Tfile = io.BytesIO()
        # use numpys built in save function to diff with prevframe
        # because we diff it it will compress more
        np.save(Tfile, img-self.prevFrame)

        # compress it into even less bytes
        b = self.C.compress(Tfile.getvalue())

        # saving prev frame
        self.prevFrame = img
        if self.Write:
            try:
                self.out.write(img)  # save frame to a video file server side
            except Exception as e:
                self.close(e)

        # send it
        try:
            send_msg(self.conn, b)
        except Exception as e:
            self.close(e)
        self.log("Sent {}KB (frame {})".format(int(len(b)/1000), self.frameno))  # debugging
        self.frameno += 1

    def startStream(self, getFrame, args=[]):
        """ Creates videostream, calls getFrame to recieve new frames, blocking
        Args:
            getFrame: Function executed to generate image frame 
            args: the argumetns passed to the getFrame function

        Returns:
            void
        """
        self.initializeStream(self.fetchFrame(getFrame, args))
        while True:
            self.sendFrame(self.fetchFrame(getFrame, args))

    def close(self, E=None):
        """Closes socket"""
        if self.Write:
            self.out.release()
        self.s.close()
        if(E!=None):
            print("Stream closed on Error\n" + E)
        else:
            self.log("Stream closed")


# this a helper for the __main__ func
def retrieveImage(cam, imgResize):
    """Basic function for retrieving camera data, for getFrame"""
    image = cv2.resize(cam.image, (0, 0), fx=imgResize, fy=imgResize)
    return image


# runs if you directly run this file
if __name__ == "__main__":
    cam = rpistream.camera.Camera(mirror=True)
    resize_cof = 1  # 960p
    server = Server(port=5000)
    server.serve()
    server.startStream(retrieveImage, [cam, resize_cof])
