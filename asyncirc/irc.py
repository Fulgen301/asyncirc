import asyncio
import collections
import importlib
import logging
import random
import ssl
from blinker import signal
loop = asyncio.get_event_loop()

connections = {}

plugins = []
def plugin_registered_handler(plugin_name):
    plugins.append(plugin_name)

signal("plugin-registered").connect(plugin_registered_handler)

def load_plugins(*plugins):
    for plugin in plugins:
        if plugin not in plugins:
            importlib.import_module(plugin)

class User:
    """
    Represents a user on IRC, with their nickname, username, and hostname.
    """
    def __init__(self, nick, user, host):
        self.nick = nick
        self.user = user
        self.host = host
        self.hostmask = "{}!{}@{}".format(nick, user, host)
        self._register_wait = 0

    @classmethod
    def from_hostmask(self, hostmask):
        if "!" in hostmask and "@" in hostmask:
            nick, userhost = hostmask.split("!", maxsplit=1)
            user, host = userhost.split("@", maxsplit=1)
            return self(nick, user, host)
        return self(None, None, hostmask)

class IRCProtocolWrapper:
    """
    Wraps an IRCProtocol object to allow for automatic reconnection. Only used
    internally.
    """
    def __init__(self, protocol):
        self.protocol = protocol

    def __getattr__(self, attr):
        if attr in self.__dict__:
            return self.__dict__[attr]
        return getattr(self.protocol, attr)

    def __attr__(self, attr, val):
        if attr == "protocol":
            self.protocol = val
        else:
            setattr(self.protocol, attr, val)

class IRCProtocol(asyncio.Protocol):
    """
    Represents a connection to IRC.
    """

    def connection_made(self, transport):
        self.work = True
        self.transport = transport
        self.wrapper = None
        self.logger = logging.getLogger("asyncirc.IRCProtocol")
        self.last_ping = float('inf')
        self.last_pong = 0
        self.lag = 0
        self.buf = ""
        self.old_nickname = None
        self.nickname = ""
        self.server_supports = collections.defaultdict(lambda *_: None)
        self.queue = []
        self.queue_timer = 1.5
        self.caps = set()
        self.registration_complete = False
        self.channels_to_join = []
        self.autoreconnect = True

        signal("connected").send(self)
        self.logger.info("Connection success.")
        self.process_queue()

    def data_received(self, data):
        if not self.work: return
        data = data.decode(errors="ignore")

        self.buf += data
        while "\n" in self.buf:
            index = self.buf.index("\n")
            line_received = self.buf[:index].strip()
            self.buf = self.buf[index + 1:]
            self.logger.debug(line_received)
            signal("raw").send(self, text=line_received)

    def connection_lost(self, exc):
        if not self.work: return
        self.logger.critical("Connection lost.")
        signal("connection-lost").send(self.wrapper)

    ## Core helper functions

    def process_queue(self):
        """
        Pull data from the pending messages queue and send it. Schedule ourself
        to be executed again later.
        """
        if not self.work: return
        if self.queue:
            self._writeln(self.queue.pop(0))
        loop.call_later(self.queue_timer, self.process_queue)

    def on(self, event):
        def process(f):
            """
            Register an event with Blinker. Convienence function.
            """
            self.logger.debug("Registering function for event {}".format(event))
            signal(event).connect(f)
            return f
        return process

    def _writeln(self, line):
        """
        Send a raw message to IRC immediately.
        """
        if not isinstance(line, bytes):
            line = line.encode("utf-8")
        self.logger.debug(line)
        self.transport.write(line + b"\r\n")
        signal("irc-send").send(line.decode(errors="ignore"))

    def writeln(self, line):
        """
        Queue a message for sending to the currently connected IRC server.
        """
        self.queue.append(line)
        return self

    def register(self, nick, user, realname, mode="+i", password=None):
        """
        Queue registration with the server. This includes sending nickname,
        ident, realname, and password (if required by the server).
        """
        self.nick = nick
        self.user = user
        self.realname = realname
        self.mode = mode
        self.password = password
        return self

    def _register(self):
        """
        Send registration messages to IRC.
        """
        if self.password:
            self.writeln("PASS {}".format(self.password))
        self.writeln("USER {0} {1} {0} :{2}".format(self.user, self.mode, self.realname))
        self.writeln("NICK {}".format(self.nick))
        self.logger.debug("Sent registration information")
        signal("registration-complete").send(self)
        self.nickname = self.nick

    ## protocol abstractions

    def join(self, channels):
        """
        Join channels. Pass a list to join all the channels, or a string to
        join a single channel. If registration with the server is not yet
        complete, this will queue channels to join when registration is done.
        """
        if not isinstance(channels, list):
            channels = [channels]
        channels_str = ",".join(channels)

        if not self.registration_complete:
            self.channels_to_join.append(channels_str)
        else:
            self.writeln("JOIN {}".format(channels_str))

        return self

    def part(self, channels):
        """
        Leave channels. Pass a list to leave all the channels, or a string to
        leave a single channel. If registration with the server is not yet
        complete, you're dumb.
        """
        if not isinstance(channels, list):
            channels = [channels]
        channels_str = ",".join(channels)
        self.writeln("PART {}".format(channels_str))

    def say(self, target_str, message):
        """
        Send a PRIVMSG to IRC.
        Carriage returns and line feeds are stripped to prevent bugs.
        """
        message = message.replace("\n", "").replace("\r", "")

        while message:
            self.writeln("PRIVMSG {} :{}".format(target_str, message[:400]))
            message = message[400:]

    def do(self, target_str, message):
        """
        Send an ACTION to IRC. Must not be longer than 400 chars.
        Carriage returns and line feeds are stripped to prevent bugs.
        """
        if len(message) <= 400:
            message = message.replace("\n", "").replace("\r", "")
            self.writeln("PRIVMSG {} :\x01ACTION {}\x01".format(target_str, message[:400]))

    def nick_in_use_handler(self):
        """
        Choose a nickname to use if the requested one is already in use.
        """
        s = "a{}".format("".join([random.choice("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ") for i in range(8)]))
        return s

    ## catch-all

    # def __getattr__(self, attr):
    #     if attr in self.__dict__:
    #         return self.__dict__[attr]

    #     def _send_command(self, *args):
    #         argstr = " ".join(args[:-1]) + " :{}".format(args[-1])
    #         self.writeln("{} {}".format(attr.upper(), argstr))

    #     _send_command.__name__ == attr
    #     return _send_command

def get_user(hostmask):
    if "!" not in hostmask or "@" not in hostmask:
        return User(hostmask, hostmask, hostmask)
    return User.from_hostmask(hostmask)

def connect(server, port=6697, use_ssl=True):
    """
    Connect to an IRC server. Returns a proxy to an IRCProtocol object.
    """
    connector = loop.create_connection(IRCProtocol, host=server, port=port, ssl=use_ssl)
    transport, protocol = loop.run_until_complete(connector)
    protocol.wrapper = IRCProtocolWrapper(protocol)
    protocol.server_info = {"host": server, "port": port, "ssl": use_ssl}
    protocol.netid = "{}:{}:{}{}".format(id(protocol), server, port, "+" if use_ssl else "-")
    signal("netid-available").send(protocol)
    connections[protocol.netid] = protocol.wrapper
    return protocol.wrapper

def disconnected(client_wrapper):
    """
    Either reconnect the IRCProtocol object, or exit, depending on
    configuration. Called by IRCProtocol when we lose the connection.
    """
    client_wrapper.protocol.work = False
    client_wrapper.logger.critical("Disconnected from {}. Attempting to reconnect...".format(client_wrapper.netid))
    signal("disconnected").send(client_wrapper.protocol)
    if not client_wrapper.protocol.autoreconnect:
        import sys
        sys.exit(2)

    connector = loop.create_connection(IRCProtocol, **client_wrapper.server_info)
    def reconnected(f):
        """
        Callback function for a successful reconnection.
        """
        client_wrapper.logger.critical("Reconnected! {}".format(client_wrapper.netid))
        _, protocol = f.result()
        protocol.register(client_wrapper.nick, client_wrapper.user, client_wrapper.realname, client_wrapper.mode, client_wrapper.password)
        protocol.channels_to_join = client_wrapper.channels_to_join
        protocol.server_info = client_wrapper.server_info
        protocol.netid = client_wrapper.netid
        protocol.wrapper = client_wrapper
        signal("netid-available").send(protocol)
        client_wrapper.protocol = protocol
    asyncio.ensure_future(connector).add_done_callback(reconnected)

signal("connection-lost").connect(disconnected)

import asyncirc.plugins.core
