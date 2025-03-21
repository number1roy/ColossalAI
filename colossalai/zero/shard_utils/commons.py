import torch
import torch.nn.functional as F
from typing import Tuple


def get_shard(tensor: torch.Tensor, rank: int, world_size: int) -> Tuple[torch.Tensor, int]:
    """Return the local shard of a full tensor."""
    # Shard using torch.chunk to match all-gather/reduce-scatter.
    chunks = list(torch.flatten(tensor).chunk(world_size))
    while len(chunks) < world_size:
        chunks.append(chunks[0].new_empty(0))

    # Determine number of padding elements.
    num_to_pad = chunks[0].numel() - chunks[rank].numel()
    assert num_to_pad >= 0, num_to_pad

    shard = chunks[rank].clone()
    if num_to_pad > 0:
        shard = F.pad(shard, [0, num_to_pad])
    return shard, num_to_pad
