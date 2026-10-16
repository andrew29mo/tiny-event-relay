import os
import socket
import subprocess
import sys
import time
import psutil
from pathlib import Path

from relay.httpio import json_request

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0))
        return sock.getsockname()[1]


def wait_for(fn,timeout=8):
    end = time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            value = fn()
            if value:
                return value
        except (OSError,ValueError):
            pass
        time.sleep(.02)
    raise AssertionError("condition did not become true within deadline")


class Child:
    def __init__(self, args, log_path):
        self.log = open(log_path,"ab")
        self.process = subprocess.Popen([sys.executable,"-m",*args],cwd=ROOT,stdout=self.log,stderr=self.log,
                                        start_new_session=True)
        self.created = psutil.Process(self.process.pid).create_time()

    def stop(self,kill=False):
        import signal
        if self.process.poll() is None:
            os.killpg(self.process.pid,signal.SIGKILL if kill else signal.SIGTERM)
            try:
                self.process.wait(timeout=6)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid,signal.SIGKILL)
                self.process.wait(timeout=3)
                raise AssertionError("child failed to stop within deadline")
        self.log.close()


class Stack:
    def __init__(self,directory,extra=()):
        self.directory = Path(directory)
        self.sink_port,self.relay_port = free_port(),free_port()
        while self.sink_port==self.relay_port:
            self.relay_port = free_port()
        self.sink_url = f"http://127.0.0.1:{self.sink_port}"
        self.url = f"http://127.0.0.1:{self.relay_port}"
        self.extra = list(extra)
        self.sink,self.relay = None,None
        self.relay_history = []

    def start_sink(self,delay=0):
        self.sink = Child(["tools.receiver","--db",str(self.directory/"sink.sqlite"),"--port",str(self.sink_port),"--delay",str(delay)],self.directory/"sink.log")
        wait_for(lambda: self.sink.process.poll() is None and json_request(self.sink_url+"/health")[0]==200)

    def start_relay(self):
        self.relay_args = ["relay","serve","--data-dir",str(self.directory/"queue"),"--upstream",self.sink_url+"/events",
                           "--port",str(self.relay_port),"--timeout","0.3","--retry-base","0.05","--retry-cap","0.2",*self.extra]
        self.relay = Child(self.relay_args,self.directory/"relay.log")
        self.relay_history.append({"pid":self.relay.process.pid,"created":self.relay.created})
        wait_for(lambda: self.relay.process.poll() is None and json_request(self.url+"/health")[0]==200)

    def start(self):
        self.start_sink()
        self.start_relay()
        return self

    def control(self,mode,delay=0):
        return json_request(self.sink_url+"/control","POST",{"mode":mode,"delay":delay})

    def submit(self,event_id,payload=None):
        return json_request(self.url+"/v1/events","POST",{"event_id":event_id,"payload":payload if payload is not None else {"value":event_id}})

    def event(self,event_id):
        return json_request(self.url+"/v1/events/"+event_id)[1]

    def delivered(self,event_id):
        return wait_for(lambda: self.event(event_id).get("state")=="delivered")

    def effects(self):
        return json_request(self.sink_url+"/effects")[1]

    def close(self):
        try:
            if self.relay:
                self.relay.stop()
        finally:
            if self.sink:
                self.sink.stop()
