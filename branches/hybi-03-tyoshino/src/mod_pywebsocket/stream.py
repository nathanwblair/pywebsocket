# Copyright 2010, Google Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
#     * Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above
# copyright notice, this list of conditions and the following disclaimer
# in the documentation and/or other materials provided with the
# distribution.
#     * Neither the name of Google Inc. nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


"""Stream of WebSocket protocol with the framing introduced by IETF HyBi 01.
"""


import struct

from mod_pywebsocket import msgutil


_OPCODE_CONTINUATION = 0
_OPCODE_CLOSE = 1
_OPCODE_PING = 2
_OPCODE_PONG = 3
_OPCODE_TEXT = 4
_OPCODE_BINARY = 5


class ConnectionTerminatedException(msgutil.ConnectionTerminatedException):
    pass


class StreamException(RuntimeError):
    pass


def _create_length_header(length, rsv4):
    header = ''

    if length <= 125:
        second_byte = rsv4 << 7 | length
        header += chr(second_byte)
    elif length < 1 << 16:
        second_byte = rsv4 << 7 | 126
        header += chr(second_byte) + struct.pack('!H', length)
    elif length < 1 << 63:
        second_byte = rsv4 << 7 | 127
        header += chr(second_byte) + struct.pack('!Q', length)
    else:
        raise StreamException('Payload is too big for one frame')

    return header


def _create_header(opcode, payload_length, more, rsv1, rsv2, rsv3, rsv4):
    header = ''

    first_byte = (more << 7
                  | rsv1 << 6 | rsv2 << 5 | rsv3 << 4
                  | opcode)
    header += chr(first_byte)
    header += _create_length_header(payload_length, rsv4)

    return header


def _create_text_frame(message):
    encoded_message = message.encode('utf-8')
    frame = _create_header(_OPCODE_TEXT, len(encoded_message), 0, 0, 0, 0, 0)
    frame += encoded_message
    return frame


def _receive_frame(request):
    received = msgutil._receive_bytes(request, 2)

    first_byte = ord(received[0])
    more = first_byte >> 7 & 1
    rsv1 = first_byte >> 6 & 1
    rsv2 = first_byte >> 5 & 1
    rsv3 = first_byte >> 4 & 1
    opcode = first_byte & 0xf

    second_byte = ord(received[1])
    rsv4 = second_byte >> 7 & 1
    payload_length = second_byte & 0x7f

    if payload_length == 127:
        extended_payload_length = msgutil._receive_bytes(request, 8)
        payload_length = struct.unpack(
            '!Q', extended_payload_length)[0]
    elif payload_length == 126:
        extended_payload_length = msgutil._receive_bytes(request, 2)
        payload_length = struct.unpack(
            '!H', extended_payload_length)[0]

    bytes = msgutil._receive_bytes(request, payload_length)

    return (opcode, bytes, more, rsv1, rsv2, rsv3, rsv4)


class Stream(object):
    """Stream of WebSocket messages."""

    # TODO(tyoshino): Add fragment support

    def __init__(self, request):
        """Construct an instance.

        Args:
            request: mod_python request.
        """
        self._request = request
        self._request.client_terminated = False
        self._request.server_terminated = False

    def send_message(self, message):
        """Send message.

        Args:
            message: unicode string to send.
        """
        if self._request.server_terminated:
            raise ConnectionTerminatedException

        msgutil._write(self._request, _create_text_frame(message))

    def receive_message(self):
        """Receive a WebSocket frame and return its payload an unicode string.

        Returns:
            payload unicode string in a WebSocket frame.
        """
        if self._request.client_terminated:
            raise ConnectionTerminatedException
        while True:
            # mp_conn.read will block if no bytes are available.
            # Timeout is controlled by TimeOut directive of Apache.

            (opcode, bytes, _, _, _, _, _) = _receive_frame(self._request)

            if opcode == _OPCODE_TEXT:
                # The Web Socket protocol section 4.4 specifies that invalid
                # characters must be replaced with U+fffd REPLACEMENT
                # CHARACTER.
                message = bytes.decode('utf-8', 'replace')
                return message
            elif opcode == _OPCODE_CLOSE:
                self._request.client_terminated = True
                raise ConnectionTerminatedException
            # Discard data of other types.

    def close_connection(self):
        """Closes a WebSocket connection."""
        if self._request.server_terminated:
            return
        # 5.3 the server may decide to terminate the WebSocket connection by
        # running through the following steps:
        # 1. send a 0xFF byte and a 0x00 byte to the client to indicate the
        # start
        # of the closing handshake.
        msgutil._write(self._request, chr(_OPCODE_CLOSE) + '\x00')
        self._request.server_terminated = True
        # TODO(ukai): 2. wait until the /client terminated/ flag has been set,
        # or until a server-defined timeout expires.
        # TODO: 3. close the WebSocket connection.
        # note: mod_python Connection (mp_conn) doesn't have close method.


# vi:sts=4 sw=4 et
