"""Local client of the root-owned fixed RADIO executor, never an N1 grant."""
from __future__ import annotations
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import socket
import struct

from .engine_lifecycle import EngineLifecycleError
from .vision_lifecycle import VisionCleanup, VisionSession

SOCKET = Path('/run/ai-platform-radio/executor.sock')


class RadioExecutorClient:
    resource_id = 'local-primary'

    def __init__(self):
        self.owner = self.session = None
        self.closed = False

    def _call(self, operation, **fields):
        payload = json.dumps({'op': operation, **fields}, allow_nan=False).encode() + b'\n'
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(2 if operation in ('health', 'verify') else 95)
            connection.connect(str(SOCKET))
            _, uid, _ = struct.unpack('3i', connection.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
            if uid != 0:
                raise EngineLifecycleError('RADIO supervisor is not root')
            connection.sendall(payload)
            reply = bytearray()
            while b'\n' not in reply and len(reply) <= 16384:
                data = connection.recv(4096)
                if not data:
                    break
                reply.extend(data)
        if len(reply) > 16384 or reply.count(b'\n') != 1:
            raise EngineLifecycleError('RADIO supervisor response invalid')
        answer = json.loads(reply)
        if type(answer) is not dict or answer.get('ok') is not True:
            raise EngineLifecycleError('RADIO supervisor rejected operation')
        return answer

    def available(self):
        # Only this fixed root-owned socket can advertise the implementation.
        # It does not change N1/N3 policy or the global GPU_REUSE_SAFE field.
        try:
            return self._call('health').get('implementation') == 'radio-legacy-exclusive-v1'
        except (OSError, ValueError, EngineLifecycleError):
            return False

    async def prepare(self, owner):
        answer = await asyncio.to_thread(self._call, 'prepare', owner=asdict(owner))
        self.owner = owner
        self.closed = False
        self.session = VisionSession(**answer['session'])
        return self.session

    def verify(self, owner, session):
        if self.closed or owner != self.owner or session != self.session:
            return False
        try:
            return self._call('verify', owner=asdict(owner), session=asdict(session)).get('active') is True
        except (OSError, ValueError, EngineLifecycleError):
            return False

    async def inspect(self, owner, session, image_id):
        if not self.verify(owner, session):
            raise EngineLifecycleError('RADIO owner mismatch')
        answer = await asyncio.to_thread(self._call, 'inspect', owner=asdict(owner),
                                        session=asdict(session), image_id=image_id)
        return answer['result']

    async def cleanup(self, owner, session):
        if not self.verify(owner, session):
            raise EngineLifecycleError('RADIO owner mismatch')
        answer = await asyncio.to_thread(self._call, 'cleanup', owner=asdict(owner), session=asdict(session))
        if (answer.get('proof') != 'SUPERVISED_SCOPE_CLOSED'
                or answer.get('owner') != asdict(owner) or answer.get('session') != asdict(session)):
            raise EngineLifecycleError('RADIO closure proof invalid')
        self.closed = True
        return VisionCleanup(owner, session, True, True, True, True)
