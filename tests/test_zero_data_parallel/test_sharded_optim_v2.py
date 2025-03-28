from functools import partial

import colossalai
import pytest
import torch
import torch.distributed as dist
import torch.multiprocessing as mp
from colossalai.amp import convert_to_apex_amp
from colossalai.nn.optimizer import CPUAdam
from colossalai.testing import parameterize
from colossalai.utils import free_port
from colossalai.zero.init_ctx import ZeroInitContext
from colossalai.zero.shard_utils import (BucketTensorShardStrategy, TensorShardStrategy)
from colossalai.zero.sharded_model import ShardedModelV2
from colossalai.zero.sharded_model.utils import col_model_deepcopy
from colossalai.zero.sharded_optim import ShardedOptimizerV2
from colossalai.zero.sharded_optim._utils import has_inf_or_nan
from colossalai.testing import rerun_on_exception
from tests.components_to_test.registry import non_distributed_component_funcs
from torch.nn.parallel import DistributedDataParallel as DDP

from common import CONFIG, check_sharded_model_params


def _run_step(model, optimizer, data, label, criterion, enable_autocast=False):
    model.train()
    optimizer.zero_grad()
    with torch.cuda.amp.autocast(enabled=enable_autocast):
        if criterion:
            y = model(data)
            loss = criterion(y, label)
        else:
            loss = model(data, label)

    loss = loss.float()
    if isinstance(model, ShardedModelV2):
        optimizer.backward(loss)
    else:
        loss.backward()
    optimizer.step()


@parameterize("cpu_offload", [True, False])
@parameterize("use_cpuadam", [True, False])
@parameterize("shard_strategy_class", [TensorShardStrategy, BucketTensorShardStrategy])
@parameterize("gpu_margin_mem_ratio", [0.0, 0.7])
def _run_test_sharded_optim_v2(cpu_offload, shard_strategy_class, use_cpuadam, gpu_margin_mem_ratio):
    test_models = ['repeated_computed_layers', 'resnet18', 'bert']
    shard_strategy = shard_strategy_class()

    if use_cpuadam and cpu_offload is False:
        return
    if gpu_margin_mem_ratio > 0.0 and not (cpu_offload and use_cpuadam):
        return

    for model_name in test_models:
        get_components_func = non_distributed_component_funcs.get_callable(model_name)
        model_builder, train_dataloader, _, optimizer_class, criterion = get_components_func()

        with ZeroInitContext(convert_fp16=True,
                             target_device=torch.device(f'cpu:0'),
                             shard_strategy=shard_strategy,
                             shard_param=True,
                             rm_torch_payload_on_the_fly=False):
            zero_model = model_builder(checkpoint=True)
        zero_model = ShardedModelV2(zero_model,
                                    shard_strategy,
                                    offload_config=dict(device='cpu') if cpu_offload else None,
                                    use_memory_tracer=gpu_margin_mem_ratio > 0.0,
                                    reuse_fp16_shard=use_cpuadam)

        model = model_builder(checkpoint=True).half()
        col_model_deepcopy(zero_model, model)
        model = model.cuda().float()

        if use_cpuadam:
            optimizer_class = CPUAdam
        optim = optimizer_class(model.parameters(), lr=1e-3)
        sharded_optim = optimizer_class(zero_model.parameters(), lr=1e-3)
        sharded_optim = ShardedOptimizerV2(zero_model,
                                           sharded_optim,
                                           cpu_offload=cpu_offload,
                                           initial_scale=2**5,
                                           gpu_margin_mem_ratio=gpu_margin_mem_ratio)

        amp_config = dict(opt_level='O2', keep_batchnorm_fp32=False)
        apex_model, apex_optimizer = convert_to_apex_amp(model, optim, amp_config)
        if dist.get_world_size() > 1:
            apex_model = DDP(apex_model)

        for i, (data, label) in enumerate(train_dataloader):
            if i > 5:
                break
            data, label = data.cuda(), label.cuda()
            _run_step(apex_model, apex_optimizer, data, label, criterion, False)
            _run_step(zero_model, sharded_optim, data, label, criterion, False)
            check_sharded_model_params(model, zero_model, loose=True, reuse_fp16_shard=use_cpuadam)
            for param in model.parameters():
                assert not has_inf_or_nan(param)


def _run_dist(rank, world_size, port):
    colossalai.launch(config=CONFIG, rank=rank, world_size=world_size, host='localhost', port=port, backend='nccl')
    _run_test_sharded_optim_v2()


# use_cpuadam = True can be used with cpu_offload = False
@pytest.mark.dist
@pytest.mark.parametrize("world_size", [1, 2])
@rerun_on_exception(exception_type=mp.ProcessRaisedException, pattern=".*Address already in use.*")
def test_sharded_optim_v2(world_size):
    run_func = partial(_run_dist, world_size=world_size, port=free_port())
    mp.spawn(run_func, nprocs=world_size)


if __name__ == '__main__':
    test_sharded_optim_v2(world_size=2)
