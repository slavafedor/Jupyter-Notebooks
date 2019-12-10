import json
from enum import Enum
import requests
import sys
import threading
from time import sleep
import websocket
from logging import getLogger

_logger = getLogger()

class JSONObjectEncoder(json.JSONEncoder):
    def default(self, obj):
        if type(obj) in PUBLIC_ENUMS.values():
            return  str(obj.value)

        if callable(obj):
            return ""

        result = obj.__dict__
        result['__class_name__'] = obj.__class__.__name__
        return result


class MistyEventInequality(Enum):
    Equal = "=="
    Greater = ">"
    GreaterOrEqual = ">="
    Less = "<"
    LessOrEqual = "<="


class EventCondition:
    Property = ""
    Inequality = MistyEventInequality.Equal
    Value = ""
    
    def __init__(self, property, ineqality, value):
        self.Property = property
        if isinstance(ineqality, MistyEventInequality):
            self.Inequality = ineqality
        self.Value = value


# global stuff
PUBLIC_ENUMS = {
    'MistyEventInequality': MistyEventInequality,
    # ...
}

_je = JSONObjectEncoder()


class MistyWsEvent:

    def __init__(self, ws_type, event_name, debounce, eventConditions, onMessage = None):
        self.Operation = "subscribe"
        self.Type = ws_type
        self.EventName = event_name
        self.DebounceMs = debounce
        self.EventConditions = []
        self.onMessage = onMessage 
        
        if isinstance(eventConditions, list) and len(eventConditions) > 0 and isinstance(eventConditions[0], EventCondition):
            for ec in eventConditions:
                self.EventConditions.append(ec)
    
    def getSubscribeMsg(self):
        return _je.encode(self)

    def getUnsubscribeMsg(self):
        return '{"Operation": "unsubscribe","EventName": "' + self.EventName + '"}'

    def onMessageReceived(self, msg):
        # Code here
        _logger.debug(msg)
        try :
            if self.onMessage != None and callable(self.onMessage):
                self.onMessage(msg)
        except:
            _logger.error( "Unexpected error:", sys.exc_info()[0])
        return


class MistyWebClient:

    def __init__(self, baseUrl):
        self.MistyEvents = dict()
        self.IsOpen = False
        self.IsInError = False
        self.IsClosed = False
        self.BaseUrl = baseUrl
        self.BaseApiUrl = "http://" + self.BaseUrl + "/api/"
        self.ConnectTimeout = 2
        self.ResponseTimeout = 20


    def getJson(self, obj):
        if hasattr(obj, "__dict__") or isinstance(obj, list):
            return _je.encode(obj)
        else:
            return obj


    def get(self, url, qs = "", headers = ""):
        return requests.get(self.BaseApiUrl + url, params = qs, headers = headers, timeout = (self.ConnectTimeout, self.ResponseTimeout))


    def post(self, url, data = None, json = None,  headers = ""):
        return requests.post(self.BaseApiUrl + url, data = data, json = json, timeout = (self.ConnectTimeout, self.ResponseTimeout))


    def put(self, url, data = None, json = None,  headers = ""):
        return requests.put(self.BaseApiUrl + url, data = data, jason = json, timeout = (self.ConnectTimeout, self.ResponseTimeout))


    def delete(self, url, qs = "", headers = ""):
        return requests.delete(self.BaseApiUrl + url, params = qs, headers = headers, timeout = (self.ConnectTimeout, self.ResponseTimeout))


    def addEvent(self, mistyWsEvent : MistyWsEvent):
        if not isinstance(mistyWsEvent, MistyWsEvent):
             raise TypeError

        self.MistyEvents.update({mistyWsEvent.EventName : mistyWsEvent})

        if self.IsOpen == True:
            self.subscribe(mistyWsEvent)


    def subscribe(self, mistyWsEvent : MistyWsEvent):
        if self.IsOpen == False:
            return

        self.unsubscribe(mistyWsEvent)

        msg = mistyWsEvent.getSubscribeMsg()
        self.ws.send(msg)
        sleep(1)


    def unsubscribe(self, mistyWsEvent : MistyWsEvent):
        if self.IsOpen == False:
            return

        msg = mistyWsEvent.getUnsubscribeMsg()
        self.ws.send(msg)
        sleep(1)


    def removeEvent(self, eventName):
         mistyWsEvent = self.MistyEvents.get(eventName, None)
         if mistyWsEvent != None:
             self.unsubscribe(mistyWsEvent)
             self.MistyEvents.popitem(eventName)


    def on_open(self):
        _logger.debug("Openned")
        self.IsOpen = True



    def on_error(self, error):
        _logger.error(error)
        self.IsInError = True


    def on_close(self):
        _logger.debug("Listening Ended")
        self.IsInError = False
        self.IsOpen = False
        self.IsClosed = True


    def on_message(self, message):
        try:
            msgParsed = self.parseMsg(message)
            if msgParsed == None : return 

            eventKey = msgParsed["eventName"]
            event = self.MistyEvents.get(eventKey)
            if event != None :
                event.onMessageReceived(msgParsed)
            _logger.debug(message)
        except:
            _logger.error("Unexpected error:", sys.exc_info()[1])
            _cnt = 10


    def parseMsg(self, msg):
        msgParsed = {}
        try:
            msgParsed = json.JSONDecoder().decode(msg)
            if type(msgParsed["message"]) is not dict : 
                if "Cannot register" in msgParsed["message"]:
                    _logger.debug(msgParsed["message"])
                    #self.stop_listener()
                    return None
                if "registered" in msgParsed["message"]:
                    _logger.debug(msgParsed["message"])
                    #self.stop_listener()
                    return None
        except:
            print("Unexpected error:", sys.exc_info()[1])
            return None

        return msgParsed


    def startListen(self, ip = "", enableTrace = False):
        if ip == "" : 
            ip = self.BaseUrl
        websocket.enableTrace(enableTrace)
        wsPath = "ws://" + ip + "/pubsub"
        self.ws = websocket.WebSocketApp(wsPath,
                                        keep_running=True,
                                        on_open=self.on_open,
                                        on_message=self.on_message,
                                        on_error=self.on_error,
                                        on_close=self.on_close)

        self.ws_thread = threading.Thread(target=self.ws.run_forever)
        self.ws_thread.daemon = True
        self.ws_thread._running = True
        self.ws_thread.start()
        print('Websocket thread started')

        cnt = 0
        while (not self.IsOpen) and cnt < 5:
            sleep(1)
            cnt += 1
        else :
            if cnt >= 5 :
                self.ws.close()
                raise TimeoutError("Cant open Web Socket")

        for e in self.MistyEvents.values():
            self.subscribe( e)

        return self.ws


    def stopListen(self):

        for e in self.MistyEvents.values():
            self.unsubscribe( e)

        self.ws.close()


def __init__():
    _logger.debug("init misty_wc")

__all__ = ["MistyEventInequality", "EventCondition", "MistyWsEvent", "MistyWebClient"]


# Tests:

def onMsg(msg):
   print(msg["message"]["distanceInMeters"])

ec = EventCondition("SensorPosition", MistyEventInequality.Equal, "Right")
tofrrEvent = MistyWsEvent("TimeOfFlight", "tof_r_r", 1000, [ec], onMsg)
print(tofrrEvent.getSubscribeMsg())
print(tofrrEvent.getUnsubscribeMsg())

# mwc = MistyWebClient("169.254.206.171")
# mwc.post("led", json='{"red":0, "green":0, "blue":250}')
# mwc.startListen()
# mwc.addEvent(tofrrEvent)
# j = mwc.getJson({"red":0, "green": 250, "blue": 0})
# print(j)
# mwc.post("led", json= j)
# sleep(5)
# mwc.post("led", json={"red":250, "green": 0, "blue": 0})
# mwc.stopListen()
# mwc.removeEvent(tofrrEvent)
# resp = mwc.post("led", json={"red":0, "green": 0, "blue": 250})
# print(resp)
