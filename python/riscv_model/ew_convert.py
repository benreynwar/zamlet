"""
Here is where I'm trying to work out what the functions are to move data between memory regions that are
using different element widths.

# src ew = 16, dst ew = 32
# (assuming 4 words in a vline)  number by 16 bits
# word            0            1            2            3
# src         0  4  8 12   1  5  9 13   2  6 10 14   3  7 11 15  
# dst         0  1  8  9   2  3 10 11   4  5 12 13   6  7 14 15
# message
#   dst word  0            1            2            3
#   src word  0     1      2     3      0     1      2     3
#   shift     -     1 ->   -     1 ->   1 <-  -      1 <-  -
#   byte mask 1010  0101   1010  0101   1010  0101   1010  0101

# src ew = 32, dst_ew = 16
# word            0            1            2            3
# src         0  1  8  9   2  3 10 11   4  5 12 13   6  7 14 15
# dst         0  4  8 12   1  5  9 13   2  6 10 14   3  7 11 15  
# message
#   dst word  0            1            2            3       
#   src word  0     2      0     2      1     3      1     3
#   shift     -     1 ->   1 <-  -      -     1 ->   1 <-  -
#   byte mask 1010  0101   1010  0101   1010  0101   1010  0101

# src ew = 8, dst ew = 32
# (assuming 4 words in a vline)  number by 8 bits
# word        0                                   1                        2                         3
# src         0  4  8 12 16 20 24 28              1  5  9 13 17 21 25 29   2  6 10 14 18 22 26 30    3  7 11 15 19 23 27 31
# dst         0  1  2  3 16 17 18 19              4  5  6  7 20 21 22 23   8  9 10 11 24 25 26 27   12 13 15 15 28 29 30 31
# message
#   dst word  0                                   1
#   src word  0        1        2        3        0
#   shift     -        1 ->     2 ->     3 ->
#   byte mask 10001000 01000100 00100010 00010001

# src ew = 8, dst ew = 32, q is the number of words in a vector
# Split the  vector into elements of ew=8.
# Here we show the r'th word in the vector for both the src
# and dst vector and which elements they contain.
# src          r     q+r    2q+r    3q+r    4q+r    5q+r    6q+r    7q+r
# dst         4r    4r+1    4r+2    4r+3   4q+4r 4q+4r+1 4q+4r+2 4q+4r+3
#
# Let's say we have dst 'm'th vector.
# We want to find out where we need to read from the src vector to get the data.
# The first element is 4m
# If  4m < q       then   src word    4m, el 0, shift is 0
# If  q <= 4m < 2q then   src word  4m-q, el 1, shift is 1 left
# If 2q <= 4m < 3q then   src word 4m-2q, el 2, shift is 2 left
# If 3q <= 4m < 4q then   src word 4m-3q, el 3, shift is 3 left
# The second element is 4m+1
# If 4m+1 < q      then   src_word  4m+1, el 0, shift is 1 right

# If 0 <= 4m < q
# src word         4m     4m+1     4m+2     4m+3       4m     4m+1     4m+2     4m+3
# shift             -     1 ->     2 ->     3 ->        -     1 ->     2 ->     3 ->

# If q <= 4m < 2q
# src word       4m-q   4m-q+1   4m-q+2   4m-q+3   4m-q+1   4m-q+1   4m-q+2   4m-q+3
# shift          1 <-        -     1 ->     2 ->     1 <-        -     1 ->     2 ->

# If 2q <= 4m < 3q
# src word      4m-2q  4m-2q+1  4m-2q+2  4m-2q+3  4m-2q+1  4m-2q+1  4m-2q+2  4m-2q+3
# shift          2 <-     1 <-        -     1 ->     2 <-     1 <-        -      1 ->

# If 3q <= 4m < 4q
# src word      4m-3q  4m-3q+1  4m-3q+2  4m-3q+3  4m-3q+1  4m-3q+1  4m-3q+2  4m-3q+3
# shift          3 <-     2 <-     1 <-        -     3 <-     2 <-     1 <-        -

# So if src ew =8 and dst ew=32
# For each word we need 4 reads
# For word m the reads are
#   x = 4m // q
#   y = 4m % q
#   src word     shift left bytes     mask
#          y                    x     10001000
#        y+1                  x-1     01000100
#        y+2                  x-2     00100010
#        y+3                  x-3     00010001

# If h is the ratio dst_ew/src_ew
# then this doesn't generalize within h <= q

Let's take a example where src_ew = 8, dst_ew = 64 and we have 4 words (64 bit)

src   0  4  8 12 16 20 24 28   1  5  9 13 17 21 25 29    2  6 10 14 18 22 26 30    3  7 11 15 19 23 27 31
dst   0  1  2  3  4  5  6  7   8  9 10 11 12 13 14 15   16 17 18 19 20 21 22 23   24 25 26 27 28 29 30 31

Maybe we can use the old method but when the src word goes past the end we wrap around, and increase shift left?
Yep, that worked.


# And the opposite direction
# src         4r    4r+1    4r+2    4r+3   4q+4r 4q+4r+1 4q+4r+2 4q+4r+3
# dst          r     q+r    2q+r    3q+r    4q+r    5q+r    6q+r    7q+r

# We want to the dst m'th word.
# The first element is 'm'.
# if m < q//2
# That can be found on the m//4'th word in the src vector.
# And it is the m % 4 element in that word.
# The second element is 'm + q'
# That can be found on the (m+q)//4th word in the src vector.
# And it is the m % 4 element in that word.

#  x = 
#  src word    shift left bytes   mask
#      m//4               m % 4   10001000
#  (m+q)//4           (m % 4)-1   01000100
# (m+2q)//4           (m % 4)-2   00100010
# (m+3q)//4           (m % 4)-3   00010001

And with ratio greater than number of words
Let's take a example where src_ew = 64, dst_ew = 8 and we have 4 words (64 bit)

src   0  1  2  3  4  5  6  7   8  9 10 11 12 13 14 15   16 17 18 19 20 21 22 23   24 25 26 27 28 29 30 31
dst   0  4  8 12 16 20 24 28   1  5  9 13 17 21 25 29    2  6 10 14 18 22 26 30    3  7 11 15 19 23 27 31

To get the first word in dst we need to do
     
src word shift a, mask a, shift b, mask b            (m+xq)//ratio   (m % ratio)-x  (m % q)-x   (m % q) + q -x   masks
   0        0       0       3       1         x=0,1      0, 0           0, -1         0, -1        4, 3          10000000, 01000000
   1       -2       2       1       3           2,3      1, 1          -2, -3        -2, -3        2, 1   
   2       -4       4      -1       5           3,4      2, 2          -3, -4        
   3       -6       6      -3       7

To get the second word in dst we need to do

src word shift a, mask a, shift b, mask b   
   0        1       0       4       1        x=0,1 y=0,1 m=1 q=4 shift_left=1,4
   1       -1       2       2       3        x=2,3 y=0,1 m=1 q=4 shift_left=
   2       -3       4       0       5        x=4,5 y=0,1 m=1 q=4
   3       -5       6      -2       7        x=6,7 y=0,1 m=1 q=4

Let x is message index
    We read page (m + xq)//ratio
    y = x % (ratio//q)
    shift_left = (m % q) + yq - x
    mask = x


It's working now for aligned movement between different ew regions.
Now to get it working for non-aligned loads.

src ew = 8, dst ew = 32
(assuming 4 words in a vline)  number by 8 bits
word        0                                   1                        2                         3
src         0  4  8 12 16 20 24 28              1  5  9 13 17 21 25 29   2  6 10 14 18 22 26 30    3  7 11 15 19 23 27 31
dst         0  1  2  3 16 17 18 19              4  5  6  7 20 21 22 23   8  9 10 11 24 25 26 27   12 13 15 15 28 29 30 31

Now let's say we want to load into dst, but we want to start the load from adress 21 in src.

This means the elements that word 0 should load are
27 28 29 30 37 38 39 40  which is 27 28 29 30 +5 +6 +7 +8   (where the + means it's from the next vector line)

27 we load from word 3

Hmm. Let's try to do it with equations.

If we have the bit_index (b), what is the vw_index (w), and the word bit, (o)
element_index = bit_index // ew
element_bit = bit_index % ew
vw_index = element_index % n_words
word_element = element_index//n_words
word_bit = word_element*ew + element_bit

And going the other way
If we have the vw_index, word_bit so should be able to get the bit_index

So know let's assume we have a dst vector with dst_ew, for a given (vw_index, word_bit) in the dst vector
and a src_ew and src_offset where is the bit in the src region.

First we find the bit_index

dst_word_element = dst_word_bit//dst_ew
dst_element_bit = dst_word_bit % dst_ew
dst_element_index = dst_word_element * n_words + dst_vw_index
dst_bit_index = dst_element_index * dst_ew + dst_element_bit
bi_d = ei_d * ew_d + eb_d
bi_d = (we_d * n + wi_d) * ew_d + eb_d
bi_d = ((wb_d//ew_d) * n + wi_d) * ew_d + (wb_d % ew_d)
bi_d = ((wb_d//ew_d) * n * ew_d) + (wi_d * ew_d) + (wb_d % ew_d)
bi_d = (wb_d//ew_d*ew_d * n) + (wi_d * ew_d) + (wb_d % ew_d)

Best way to think about this is that we take the two integers word_index and word_bit.
The bit_integer number takes the low bits of the word_bit then all the bits of the word_index and then the high bits of the word_bit.

The source bit will bo
bi_s = bi_d + offset


Theory based on drawing pictures. Should make a nice diagram at some point.

First take the case where dst_ew > src_ew
ratio = dst_ew//src_ew

The question is for a given dst_word and src_word how to determine many sections from src_word need to retrieved to make dst_word.

The upper log2(n_words//ratio) bits of the src word index we always be the same as the lower bits of the dst word_index.
The lower log2(ratio) bits of the src word index are the same as the upper bits in the element_bit address.
So fixing the src_word tells us src_ew sized chunk in a dst_ew sized element we're fetching data for.
The upper log2(word_bits//dst_ew) of the element in word index are the same in the src and dst locations. This determines the number
of sections that we need to retrieve. (i.e. there will be word_bits//dst_ew sections to copy)
We will always need to copy from `ratio` different src words.

How does having an offset change things?

Our dst address will convert into a src address, but it might now be in the middle of a src element rather than at the beginning.
Incrementing our bit address in the dst element will still increment the bit address in the src element. When the src element rolls
over we'll start incrementing the lower bits of the word_index (and so we're in a different word which we don't care about). We'll roll
over `ratio` lower bits in the word index before we start rolling over bits in the 'element in word'.  We might have word_bits/dst_ew
complete sections to copy, or we might have a partial setion followed by `words_bits/dst_ew-1` complete sections followed by another
partial section.

Let's try to come up with some equations for how to get the shifts and the masks.

We're working on word `m`.  `m_U` is the integer of the upper `ratio` bits of m. and `m_L` are the remaining lower bits.
We'll use m = m_U ++ m_L to represent the bit concatentation of the two integers.

We find the src_address corresponding to this dst_address.
We copy either a partial src_el or a full src_el depending of whether we are at the start of a src_el.
The shift is determined by subtracing the src bit_in_word from the dst bit_in_word

Now go back to the start of that src_el, and increment the upper 'word_bits/dst_el_bits' of the element_in_word index.
Whether the shift changes will depend on which the upper `ratio` bits of the 




"""

from random import Random
from dataclasses import dataclass
from typing import List

from params import LamletParams


def get_rand_bytes(rnd: Random, n: int):
    #ints = [rnd.getrandbits(8) for i in range(n)]
    ints = [i % 256 for i in range(n)]
    return bytes(ints)


def byte_to_bits(byt: int):
    assert 0 <= byt < 256
    bits = []
    for _ in range(8):
        bits.append(byt & 1)
        byt = byt >> 1
    assert byt == 0
    return bits


def bytes_to_bits(byts: bytes):
    bits = []
    for byt in byts:
        bits += byte_to_bits(byt)
    return bits


def bits_to_bytes(bits: List[int]):
    assert len(bits) % 8 == 0
    assert all(bit in (0, 1) for bit in bits)
    byt = 0
    byts = []
    f = 1
    for index, bit in enumerate(bits):
        byt += bit * f
        f = f << 1
        if index % 8 == 7:
            byts.append(byt)
            byt = 0
            f = 1
    byts = bytes(byts)
    return byts


def uint_to_list_of_uints(value: int, width: int, length: int):
    reduced = value
    ints = []
    f = 1 << width
    for index in range(length):
        ints.append(reduced % f)
        reduced = reduced >> width
    assert reduced == 0
    return ints


def bits_to_int(bits: List[int]):
    value = 0
    for bit in reversed(bits):
        value = value << 1
        value += bit
    return value


def encode_into_words(params: LamletParams, data: bytes, ew: int):
    print(f'encoding to ew {ew} data {[int(x) for x in data]}')
    assert len(data) == params.vline_bytes
    bits = bytes_to_bits(data)
    n_elements = params.vline_bytes*8//ew
    elements = [bits[n*ew: (n+1)*ew] for n in range(n_elements)]
    n_words = params.j_in_l
    words = [[] for i in range(n_words)]
    for el_index in range(n_elements):
        words[el_index % n_words] += elements[el_index]
    for index in range(n_words):
        words[index] = bits_to_bytes(words[index])
    print(f'result is {[[int(x) for x in data] for data in words]}')
    return words


def decode_from_words(params: LamletParams, words: List[bytes], ew: int):
    n_words = params.j_in_l
    assert len(words) == n_words
    assert all(len(word) == params.word_bytes for word in words)
    #bits = bytes_to_bits(data)
    n_elements = params.vline_bytes*8//ew
    #elements = [bits[n*ew: (n+1)*ew] for n in range(n_elements)]
    #n_words = params.j_in_L
    #words = [[] for i in range(n_words)]
    bit_words = [bytes_to_bits(word) for word in words]
    bits = []
    for el_index in range(n_elements):
        word_index = el_index % n_words
        el_in_word = el_index//n_words
        el_bits = bit_words[word_index][el_in_word*ew: (el_in_word+1)*ew]
        bits += el_bits
    data = bits_to_bytes(bits)
    return data


@dataclass
class GetWordMessage:

    vw_index: int
    shift_left: int
    bit_mask: int


def extract_words(params: LamletParams, src_words: List[List[int]], messages: List[List[GetWordMessage]]):
    word_mask = (1 << params.word_bytes*8) - 1
    words = []
    for word_index, word_messages in enumerate(messages):
        word = 0
        for msg_index, message in enumerate(word_messages):
            src_word = src_words[message.vw_index]
            src_word_int = int.from_bytes(src_word, byteorder='little', signed=False)
            print(f'vw_index {word_index} msg_index {msg_index}')
            print(f'src_word is {[int(x) for x in src_word]}')
            if message.shift_left < 0:
                shifted = (src_word_int << (-message.shift_left)) & word_mask
            else:
                shifted = src_word_int >> message.shift_left
            print(f'shifted is {uint_to_list_of_uints(shifted, 8, params.word_bytes)}')
            masked = shifted & message.bit_mask
            print(f'masked is {uint_to_list_of_uints(masked, 8, params.word_bytes)}')
            old_word = word
            word = word & (~message.bit_mask)
            word = word | masked
            print(f'word is {uint_to_list_of_uints(word, 8, params.word_bytes)}')
            old_word_bytes = old_word.to_bytes(params.word_bytes, byteorder='little', signed=False)
            word_bytes = word.to_bytes(params.word_bytes, byteorder='little', signed=False)
        byts = word.to_bytes(params.word_bytes, byteorder='little', signed=False)
        words.append(byts)
    return words

#   x = 4m // q
#   y = 4m % q
#   src word     shift left bytes     mask
#          y                    x     10001000
#        y+1                  x-1     01000100
#        y+2                  x-2     00100010
#        y+3                  x-3     00010001


def split_by_factors(value, factors):
    reduced = value
    pieces = []
    for factor in factors:
        pieces.append(reduced % factor)
        reduced = reduced//factor
    assert reduced == 0
    return pieces


def join_by_factors(values, factors):
    assert len(values) == len(factors)
    f = 1
    total = 0
    for value, factor in zip(values, factors):
        assert value < factor
        total += value * f
        f *= factor
    return total


def create_messages_two(params: LamletParams, src_ew: int, dst_ew: int, offset: int):
    ww = params.word_bytes * 8
    assert dst_ew >= src_ew
    ratio = dst_ew//src_ew
    messages = []
    for dst_vw in range(params.j_in_l):   # word in vector
        uses = {}
        for index in range(dst_ew//src_ew):
            dst_eb = src_ew * index
            src_ebs = []
            for dst_we in range(ww//dst_ew):
                dst_wb = join_by_factors([dst_we, dst_eb],  [ww//dst_ew, dst_ew])
                #dst_vw_U, dst_vw_L = split_by_factors(dst_vw, [ratio, params.j_in_l//ratio])
                #dst_eb_U, dst_eb_L = split_by_factors(dst_eb, [ratio, src_ew])
                logical_address = join_by_factors([dst_eb, dst_vw, dst_we], [dst_ew, params.j_in_l, ww//dst_ew])
                offset_address = logical_address + offset
                src_eb, src_vw, src_we = split_by_factors(offset_address, [src_ew, params.j_in_l, ww//src_ew])
                src_wb = join_by_factors([src_eb, src_we], [src_ew, ww/src_ew])
                shift = src_wb - dst_wb
                mask = [0] * ww
                mask[src_we*src_ew+src_eb: (src_we+1)*src_ew] = [1] * (src_ew-src_eb)
                if src_vw not in uses:
                    uses[src_vw] = []
                uses[src_vw].append((shift, mask))
                src_ebs.append(src_eb)
                print(f'------')
                print(f'dst_vw = {dst_vw}, dst_eb = {dst_eb}, dst_we = {dst_we}')
                print(f'offset address is {offset_address}')
                print(f'src_vw = {src_vw}, src_eb = {dst_eb}, src_we = {dst_we}')
                print(f'shift is {shift}, mask is {mask}')
            # # As we increment dst_we we increment src_we_U. That will give us a similar segment for a different element in the word.
            # # Because src_we_U maps to the upper bits of the logical address any increase by a multiple of the src_we_U
            # # factor cannot effect any other bits in the address, since it can't overflow into another region.
            # # The shift won't change because this will change the src_wb and dst_wb by the same amount.
            # # The mask will change in a simple way that just shifts the ones.
            # # The src_vw should stay the same
            # assert len(uses) == 1
            # assert len(set(x.shift for x in uses.values())) == 1
            # assert len(set(src_ebs)) == 1
            prev_src_eb = src_ebs[0]

            # Now let's get the other half of those segments if we only got partial segments.
            if prev_src_eb != 0:
                required_bits = prev_src_eb
                for dst_we in range(ww//dst_ew):
                    dst_eb = src_ew - src_eb
                    dst_wb = join_by_factors([dst_eb, dst_we],  [dst_ew, ww/dst_ew])
                    logical_address = join_by_factors([dst_eb, dst_vw, dst_we], [dst_ew, params.j_in_l, ww//dst_ew])
                    offset_address = logical_address + offset
                    src_eb, src_vw, src_we = split_by_factors(offset_address, [src_ew, params.j_in_l, ww//src_ew])
                    src_wb = join_by_factors([src_wb, src_we], [src_ew, ww/src_ew])
                    # We expect that the src_vw has incremented since the overflow from src_eb will flow into that
                    # The shift will also be different since the overflow will effect the wb in src and dst differently.
                    shift = src_wb - dst_wb
                    mask = [0] * ww
                    mask[src_we*src_ew+src_eb: src_ew*src_ew+src_eb+required_bits] = [1]
                    if src_vw not in uses:
                        uses[src_vw] = []
                    uses[src_vw].append((shift, mask))
        word_messages = []
        for src_vw, shifts_and_masks in uses.items():
            for shift, mask in shifts_and_masks:
                message = GetWordMessage(
                    vw_index=src_vw,
                    shift_left=shift,
                    bit_mask=mask,
                    )
                word_messages.append(message)
        messages.append(word_messages)
    return messages













        
        # But these were potentially only partial elements.
        # To get the other parts we go back to the end of the original (src_we - src_wb) bits segment.
        # If we increment again we will roll over the dst_eb bits, and increment the dst_vw bits.
        # The second half of all these segments can be found in this src word.

        # We've now got mappings for one src_ew worth of bits in every dst_ew bits.
        # So we now need to incrememt the dst_vw 'ratio' number of times
        





def create_messages(params: LamletParams, src_ew: int, dst_ew: int):
    messages = []
    for vw_index in range(params.j_in_l):
        word_messages = []
        if src_ew <= dst_ew:
            ratio = dst_ew//src_ew
            x = (ratio * vw_index) // params.j_in_l
            y = (ratio * vw_index) % params.j_in_l
            for index in range(ratio):
                bit_mask = [0] * index * src_ew + [1] * src_ew + [0] * ((ratio-1-index) * src_ew)
                bit_mask = bit_mask * (params.word_bytes*8//src_ew//ratio)
                assert len(bit_mask) == params.word_bytes * 8
                bit_mask = bits_to_int(bit_mask)
                if ratio <= params.j_in_l:
                    assert y+index < params.j_in_l
                    message = GetWordMessage(
                        vw_index=y+index,
                        shift_left=(x-index) * src_ew,
                        bit_mask=bit_mask,
                        )
                else:
                    v = (y + index) % params.j_in_l
                    w = (y + index) // params.j_in_l
                    # We have multiple GetWordMessage for the same source word.
                    # Actually we'll only send a single read request to that node, but
                    # when we retrieve the data we'll do multiple shifts with different
                    # masks to apply the update.
                    message = GetWordMessage(
                        vw_index=v,
                        shift_left=(x-index+w) * src_ew,
                        bit_mask=bit_mask,
                        )

                word_messages.append(message)
        else:
#  src word    shift left bytes   mask
#      m//4               m % 4   10001000
#  (m+q)//4           (m % 4)-1   01000100
# (m+2q)//4           (m % 4)-2   00100010
# (m+3q)//4           (m % 4)-3   00010001
            ratio = src_ew//dst_ew
            for index in range(ratio):
                src_vw_index = (vw_index + index * params.j_in_l)// ratio
                shift_left = ((vw_index % ratio) - index) * dst_ew
                bit_mask = [0] * index * dst_ew + [1] * dst_ew + [0] * ((ratio-1-index) * dst_ew)
                bit_mask = bit_mask * (params.word_bytes*8//dst_ew//ratio)
                assert len(bit_mask) == params.word_bytes * 8
                bit_mask = bits_to_int(bit_mask)
                if ratio <= params.j_in_l:
                    assert src_vw_index < params.j_in_l
                    message = GetWordMessage(
                        vw_index=src_vw_index,
                        shift_left=shift_left,
                        bit_mask=bit_mask,
                        )
                else:
                    y = index % (ratio//params.j_in_l)
                    shift_left = ((vw_index % params.j_in_l) + y * params.j_in_l - index) * dst_ew
                    message = GetWordMessage(
                        vw_index=src_vw_index,
                        shift_left=shift_left,
                        bit_mask=bit_mask,
                        )
                word_messages.append(message)
        messages.append(word_messages)
    return messages

class SmallParams:

    word_bytes: int = 1
    vline_bytes: int = 4
    j_in_l: int = 4


def apply_offset(rnd, data: bytes, offset: int):
    bits = bytes_to_bits(data)
    fresh_bits = [rnd.getrandint(0, 1) for _ in range(offset)]
    if offset > 0:
        bits = fresh_bits + bits[:-offset]
    else:
        bits = bits[offset:] + fresh_bits
    byts = bits_to_bytes(bits)
    return byts


def test_convertion(params: LamletParams, src_ew: int, dst_ew: int, offset: int):
    rnd = Random(0)
    vlb = params.vline_bytes
    random_data = get_rand_bytes(rnd, vlb*3)
    shifted_data = apply_offset(rnd, random_data, offset)
    src_words = encode_into_words(params, random_data, src_ew)
    expected_dst_words = encode_into_words(params, shifted_data[vlb: 2*vlb], dst_ew)
    print(f'src_words = {[[int(x) for x in word] for word in src_words]}')
    print(f'expected_dst_words = {[[int(x) for x in word] for word in expected_dst_words]}')
    messages = create_messages_two(params=params, src_ew=src_ew, dst_ew=dst_ew, offset=offset)
    #messages = create_messages(params, src_ew, dst_ew)
    dst_words = extract_words(params, src_words[0], src_words[1], src_words[2], messages)
    rcvd_data = decode_from_words(params, dst_words, dst_ew)
    assert random_data == rcvd_data


def main():
    params = SmallParams()
    for src_ew in (1, 2, 4, 8):#, 16, 32, 64):
        for dst_ew in (1, 2, 4, 8):#, 16, 32, 64):
            if dst_ew >= src_ew:
                offset = 35
                test_convertion(params, src_ew, dst_ew, offset)


if __name__ == '__main__':
    main()
