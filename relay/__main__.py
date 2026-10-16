import argparse
import json
import signal

from .httpio import json_request
from .service import Relay


def positive(value):
    number = float(value)
    if not 0<number<float("inf"):
        raise argparse.ArgumentTypeError("must be finite and positive")
    return number


def positive_int(value):
    number = int(value)
    if number<=0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def main():
    parser = argparse.ArgumentParser(description="Bounded durable local event relay")
    commands = parser.add_subparsers(dest="command",required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--data-dir",required=True)
    serve.add_argument("--upstream",required=True)
    serve.add_argument("--port",type=int,default=8080)
    for name,default in [("timeout",2),("retry-base",.25),("retry-cap",30),("retry-age",86400),("receipt-ttl",86400)]:
        serve.add_argument("--"+name,type=positive,default=default)
    for name,default in [("max-events",1000),("max-payload-bytes",8*1024*1024),("disk-budget",64*1024*1024),
                         ("min-free",16*1024*1024),("receipt-limit",10000),("max-event-bytes",65536)]:
        serve.add_argument("--"+name,type=positive_int,default=default)
    for name in ("stats","get","dead-letters","requeue","submit"):
        item = commands.add_parser(name)
        item.add_argument("--url",default="http://127.0.0.1:8080")
        if name in ("get","requeue","submit"):
            item.add_argument("event_id")
        if name=="submit":
            item.add_argument("payload",help="JSON payload")
    args = vars(parser.parse_args())
    command = args.pop("command")
    if command=="serve":
        relay = Relay(directory=args.pop("data_dir"),**args)
        signal.signal(signal.SIGTERM,relay.signal_stop)
        signal.signal(signal.SIGINT,relay.signal_stop)
        relay.run()
        if relay.worker_error:
            raise SystemExit("delivery worker failed: "+relay.worker_error)
    else:
        url = args["url"].rstrip("/")
        from urllib.parse import quote
        if command=="stats":
            path,method,value = "/v1/stats","GET",None
        elif command=="dead-letters":
            path,method,value = "/v1/dead-letters","GET",None
        elif command=="submit":
            path,method,value = "/v1/events","POST",{"event_id":args["event_id"],"payload":json.loads(args["payload"])}
        else:
            path = "/v1/"+("events/" if command=="get" else "requeue/")+quote(args["event_id"],safe="")
            method,value = ("GET",None) if command=="get" else ("POST",{})
        status,result = json_request(url+path,method,value)
        print(json.dumps(result,indent=2))
        if status>=400:
            raise SystemExit(1)


if __name__=="__main__":
    main()
