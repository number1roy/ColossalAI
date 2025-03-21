import torch
import torch.distributed as dist
from typing import Optional


class ShardedTensor(object):

    def __init__(self, tensor: torch.Tensor, process_group: Optional[dist.ProcessGroup] = None) -> None:
        r"""
        A tensor sharded in multiple processes. Constructed from an existing torch.Tensor instance.
        """
        self._payload = tensor
        self.process_group = process_group
        self.world_size = dist.get_world_size(self.process_group)
        self.local_rank = dist.get_rank(self.process_group)
        self._is_sharded = False

        self._origin_shape = tensor.shape
        self._origin_numel = tensor.numel()
        self._origin_dtype = tensor.dtype

    @property
    def origin_numel(self):
        return self._origin_numel

    @property
    def origin_shape(self):
        return self._origin_shape

    @property
    def is_sharded(self):
        return self._is_sharded

    @is_sharded.setter
    def is_sharded(self, flag: bool):
        self._is_sharded = flag

    @property
    def payload(self):
        return self._payload

    def copy_payload(self, tensor):
        self._payload.view(-1).copy_(tensor.view(-1))

    def reset_payload(self, tensor):
        del self._payload
        self._payload = tensor

    @property
    def device(self):
        return self._payload.device

    @property
    def dtype(self):
        assert self._payload.dtype == self._origin_dtype
        return self._origin_dtype

    def to(self, device: torch.device):
        raise RuntimeError("Use colo_model_tensor_move install of call .to() on ShardedTensor")

    def to_(self, device: torch.device):
        raise RuntimeError("Use colo_model_tensor_move install of call .to_() on ShardedTensor")

    @property
    def shape(self):
        return self._payload.shape
