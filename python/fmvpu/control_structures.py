from typing import List, Tuple, Dict, Any
import logging


logger = logging.getLogger(__name__)


def pack_value_to_bits(value, width: int) -> List[bool]:
    """Pack a value into a list of bits (LSB first)."""
    bits = []
    for i in range(width):
        bits.append((value >> i) & 1 == 1)
    return bits


def pack_fields_to_bits(obj, field_specs: List[Tuple[str, int]]) -> List[bool]:
    """Pack object fields into a list of bits using field specifications.
    
    Args:
        obj: Object containing the fields
        field_specs: List of (field_name, bit_width) tuples
    
    Returns:
        List of bits (LSB first), packed in reverse field order to match Chisel's asUInt behavior
    """
    all_bits = []
    
    # Pack fields in reverse order to match Chisel's Bundle.asUInt behavior
    for field_name, bit_width in reversed(field_specs):
        value = getattr(obj, field_name)
        
        if isinstance(value, bool):
            all_bits.append(value)
        elif isinstance(value, int):
            all_bits.extend(pack_value_to_bits(value, bit_width))
        elif isinstance(value, list):
            if isinstance(value[0], bool):
                all_bits.extend(value)
            elif isinstance(value[0], int):
                for item in value:
                    all_bits.extend(pack_value_to_bits(item, bit_width // len(value)))
            else:
                raise ValueError(f"Unsupported list type for field {field_name}")
        else:
            raise ValueError(f"Unsupported field type for {field_name}: {type(value)}")
    
    return all_bits


def pack_bits_to_words(bits: List[bool], word_width: int = 32) -> List[int]:
    """Pack a list of bits into words."""
    words = []
    for i in range(0, len(bits), word_width):
        word = 0
        for j in range(min(word_width, len(bits) - i)):
            if bits[i + j]:
                word |= (1 << j)
        words.append(word)
    return words


def pack_fields_to_words(obj, field_specs: List[Tuple[str, int]], word_width: int = 32) -> List[int]:
    """Pack object fields into words using field specifications."""
    bits = pack_fields_to_bits(obj, field_specs)
    return pack_bits_to_words(bits, word_width)


def unpack_words_to_fields(words: List[int], field_specs: List[Tuple[str, int]], word_width: int = 32) -> Dict[str, Any]:
    """Unpack words into field values using field specifications."""
    # Convert words back to bits
    bits = []
    for word in words:
        for i in range(word_width):
            bits.append((word >> i) & 1 == 1)
    
    # Extract fields from bits (reverse order to match packing)
    field_values = {}
    bit_offset = 0
    
    for field_name, bit_width in reversed(field_specs):
        value = 0
        for i in range(bit_width):
            if bits[bit_offset + i]:
                value |= (1 << i)
        field_values[field_name] = value
        bit_offset += bit_width
    
    return field_values


def calculate_total_width(field_specs: List[Tuple[str, int]]) -> int:
    """Calculate total width in bits from field specifications."""
    return sum(width for _, width in field_specs)
