from typing import Callable, Dict, Any, List

from zamlet.message import MessageType


# Registry mapping MessageType -> handler function
# Handler signature: async def handler(jamlet, packet: List[Any]) -> None
MESSAGE_HANDLERS: Dict[MessageType, Callable] = {}


def register_handler(message_type: MessageType):
    '''Decorator to register a message handler for a given MessageType.'''
    def decorator(func):
        MESSAGE_HANDLERS[message_type] = func
        return func
    return decorator


# Import transaction modules to register their handlers
from zamlet.transactions import load_j2j_words
from zamlet.transactions import store_j2j_words
from zamlet.transactions import load_word
from zamlet.transactions import store_word
from zamlet.transactions import read_mem_word
from zamlet.transactions import write_mem_word
from zamlet.transactions import store_stride
from zamlet.transactions import read_reg_element
