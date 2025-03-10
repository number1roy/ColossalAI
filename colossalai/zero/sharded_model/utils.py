import torch
from colossalai.zero.sharded_model import ShardedModelV2

import copy


def col_model_deepcopy(sharded_model: ShardedModelV2, other_model: torch.nn.Module):
    """
    copy param of the ShardedModelV2 to other_model.
    Note the other_model has to be the same as self.
    """
    for zero_param, param in zip(sharded_model.parameters(), other_model.parameters()):
        assert hasattr(zero_param, 'col_attr')
        shard_flag = zero_param.col_attr.sharded_data_tensor.is_sharded
        if shard_flag:
            sharded_model.shard_strategy.gather([zero_param.col_attr.sharded_data_tensor])
        param.data = copy.deepcopy(zero_param.col_attr.sharded_data_tensor.payload)
        if shard_flag:
            sharded_model.shard_strategy.shard([zero_param.col_attr.sharded_data_tensor])
