from enum import IntEnum

from zamlet.moore import moore_d2xy, moore_xy2d


class LaneOrder(IntEnum):
    MOORE = 0
    UNKNOWN1 = 1
    ROW_MAJOR = 2
    TOROIDAL_ROW_MAJOR = 3
    COLUMN_MAJOR = 4
    TOROIDAL_COLUMN_MAJOR = 5

    @classmethod
    def count(cls) -> int:
        return len(cls)


def vw_index_to_j_coords(params, lane_order: LaneOrder, vw_index: int):
    if lane_order == LaneOrder.ROW_MAJOR:
        jx = vw_index % (params.j_cols * params.k_cols)
        jy = vw_index // (params.j_cols * params.k_cols)
        return jx, jy
    if lane_order == LaneOrder.MOORE:
        total_cols = params.j_cols * params.k_cols
        total_rows = params.j_rows * params.k_rows
        assert total_cols == total_rows, (
            f"MOORE requires square grid, got {total_cols}x{total_rows}"
        )
        assert total_cols & (total_cols - 1) == 0, (
            f"MOORE requires power-of-2 grid, got {total_cols}"
        )
        return moore_d2xy(total_cols, vw_index)
    if lane_order == LaneOrder.COLUMN_MAJOR:
        total_rows = params.j_rows * params.k_rows
        jx = vw_index // total_rows
        jy = vw_index % total_rows
        return jx, jy
    if lane_order == LaneOrder.TOROIDAL_ROW_MAJOR:
        total_cols = params.j_cols * params.k_cols
        total_rows = params.j_rows * params.k_rows
        assert total_rows >= 2
        row_rank = vw_index // total_cols
        ordered_x = vw_index % total_cols
        if row_rank < (total_rows + 1) // 2:
            y = row_rank * 2
        else:
            y = 2 * (total_rows - 1 - row_rank) + 1
        x = total_cols - 1 - ordered_x if row_rank % 2 else ordered_x
        return x, y
    if lane_order == LaneOrder.TOROIDAL_COLUMN_MAJOR:
        total_cols = params.j_cols * params.k_cols
        total_rows = params.j_rows * params.k_rows
        assert total_cols >= 2
        col_rank = vw_index // total_rows
        ordered_y = vw_index % total_rows
        if col_rank < (total_cols + 1) // 2:
            x = col_rank * 2
        else:
            x = 2 * (total_cols - 1 - col_rank) + 1
        y = total_rows - 1 - ordered_y if col_rank % 2 else ordered_y
        return x, y
    raise NotImplementedError(f"Lane order {lane_order}")


def vw_index_to_routing_coords(params, lane_order: LaneOrder, vw_index: int):
    jx, jy = vw_index_to_j_coords(params, lane_order, vw_index)
    return jx + params.west_offset, jy + params.north_offset


def j_coords_to_vw_index(params, lane_order: LaneOrder, jx: int, jy: int):
    if lane_order == LaneOrder.ROW_MAJOR:
        return jy * (params.j_cols * params.k_cols) + jx
    if lane_order == LaneOrder.MOORE:
        total_cols = params.j_cols * params.k_cols
        total_rows = params.j_rows * params.k_rows
        assert total_cols == total_rows, (
            f"MOORE requires square grid, got {total_cols}x{total_rows}"
        )
        assert total_cols & (total_cols - 1) == 0, (
            f"MOORE requires power-of-2 grid, got {total_cols}"
        )
        return moore_xy2d(total_cols, jx, jy)
    if lane_order == LaneOrder.COLUMN_MAJOR:
        return jx * (params.j_rows * params.k_rows) + jy
    if lane_order == LaneOrder.TOROIDAL_ROW_MAJOR:
        total_cols = params.j_cols * params.k_cols
        row_pair = jy >> 1
        row_rank = (params.j_rows * params.k_rows - 1) - row_pair if jy & 1 else row_pair
        ordered_x = (total_cols - 1) - jx if row_rank & 1 else jx
        return row_rank * total_cols + ordered_x
    if lane_order == LaneOrder.TOROIDAL_COLUMN_MAJOR:
        total_rows = params.j_rows * params.k_rows
        col_pair = jx >> 1
        col_rank = (params.j_cols * params.k_cols - 1) - col_pair if jx & 1 else col_pair
        ordered_y = (total_rows - 1) - jy if col_rank & 1 else jy
        return col_rank * total_rows + ordered_y
    raise NotImplementedError(f"Lane order {lane_order}")


def vw_index_to_k_indices(params, lane_order: LaneOrder, vw_index: int):
    jx, jy = vw_index_to_j_coords(params, lane_order, vw_index)
    kx = jx // params.j_cols
    ky = jy // params.j_rows
    k_index = ky * params.k_cols + kx
    j_in_k_x = jx % params.j_cols
    j_in_k_y = jy % params.j_rows
    j_in_k_index = j_in_k_y * params.j_cols + j_in_k_x
    return k_index, j_in_k_index


def k_indices_to_j_coords(params, k_index: int, j_in_k_index: int):
    kx = k_index % params.k_cols
    ky = k_index // params.k_cols
    j_in_k_x = j_in_k_index % params.j_cols
    j_in_k_y = j_in_k_index // params.j_cols
    jx = kx * params.j_cols + j_in_k_x
    jy = ky * params.j_rows + j_in_k_y
    return jx, jy


def k_indices_to_routing_coords(params, k_index: int, j_in_k_index: int):
    jx, jy = k_indices_to_j_coords(params, k_index, j_in_k_index)
    return jx + params.west_offset, jy + params.north_offset


def k_indices_to_vw_index(
    params, lane_order: LaneOrder, k_index: int, j_in_k_index: int,
):
    jx, jy = k_indices_to_j_coords(params, k_index, j_in_k_index)
    return j_coords_to_vw_index(params, lane_order, jx, jy)
