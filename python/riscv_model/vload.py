from params import LamletParams
import kinstructions

#class Load(KInstr):
#    """
#    A load from the VPU memory into a vecto register.
#    If k_maddr.addr is located just before a page boundary such that the
#    first element is split across two pages, only the second half of the element
#    is written.
#    If the last element is split across two pages, only the first half is
#    written.
#    The other elements are guaranteed to be on the same page.
#    """
#    dst: int
#    k_maddr: KMAddr  # An address in the kamlet address space
#    start_index: int
#    n_elements: int
#    dst_ordering: addresses.Ordering  # src ordering is held in k_maddr
#    src_offset: int
#    mask_reg: int
#    writeset_ident: int
#
#    async def update_kamlet(self, kamlet):
#        await kamlet.handle_load_aligned_instr(self)


def handle_vload_instr(params: LamletParams, kinstr: kinstructions.Load, vw_index: int):
    dst_ew = kinstr.dst_ordering_ew
    src_ew = kinstr.k_maddr.ordering.ew
    min_ew = min(dst_ew, src_ew)
    max_ew = max(dst_ew, src_ew)
    ew_ratio = max_ew//min_ew
    is_word_aligned = (kinstr.k_maddr.addr % params.word_bytes == 0)
    if min_ew > 1:
        is_element_aligned = (kinstr.k_maddr.addr % (min_ew//8) == 0)
    else:
        is_element_aligned = True
    if is_word_aligned:
        # We need to do `ew_ratio` ReadWord messages
        for message_index in range(ew_ratio):
            """
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

            """

            

            # message    
            #   dst word  m         
            #   src word  m         m+1       2         3
            #   shift     -         1 ->      2 ->      3 ->
            #   mask      10001000  01000100  00100010  00010001
            ew_vwindex =  
            src_vwindex = vw_index + (kinstr.k_maddr.addr % params.vline_bytes)//params.word_bytes
            byte_mask = 



    if kinstr.dst_ordering.ew <= kinstr.k_maddr.src_ordering:
        # What elements does this jamlet need to retrieve.
        first_eline = kinstr.start_index//params.j_in_l
        last_eline = (kinstr.start_index + kinstr.n_elements + params.j_in_l - 1)//params.j_in_l
        for eline_index in range(first_eline, last_eline+1):
            element_index = eline_index * params.j_in_l + vw_index
            if element_index < kinstr.start_index or element_index >= kinstr.start_index + kinstr.n_elements:
                continue

