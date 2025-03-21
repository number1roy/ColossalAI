#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from typing import List, Tuple, Union
import torch
import torch.distributed as dist

from colossalai.context.parallel_mode import ParallelMode
from colossalai.core import global_context as gpc
from colossalai.utils import get_current_device
from functools import reduce
import operator
from .utils import split_tensor_into_1d_equal_chunks, gather_split_1d_tensor


TensorShape = Union[torch.Size, List[int], Tuple[int]]


def _get_tensor_shape(tensor_shape: TensorShape, chunk_tensor: bool = False) -> Tuple[TensorShape, bool]:
    """get the exact tensor shape when communicating and return whether the tensor is a chunk

    :param tensor_shape: shape of tensor
    :type tensor_shape: TensorShape
    :param chunk_tensor: whether to chunk tensor, defaults to False
    :type chunk_tensor: bool, optional
    :return: exact tensor shape, whether to chunk tensor
    :rtype: Tuple[Union[torch.Size, List[int], Tuple[int]], bool]
    """
    if chunk_tensor:
        tensor_chunk_shape = reduce(operator.mul, tensor_shape, 1)
        tensor_parallel_world_size = gpc.get_world_size(ParallelMode.TENSOR)
        if tensor_chunk_shape % tensor_parallel_world_size == 0:
            tensor_chunk_shape = tensor_chunk_shape // tensor_parallel_world_size
        else:
            tensor_chunk_shape = tensor_shape
            chunk_tensor = False
    else:
        tensor_chunk_shape = tensor_shape
    return tensor_chunk_shape, chunk_tensor


def _communicate(tensor_send_next=None,
                 tensor_send_prev=None,
                 recv_prev=False,
                 recv_next=False,
                 recv_prev_shape=None,
                 recv_next_shape=None,
                 prev_rank=None,
                 next_rank=None,
                 dtype=None,
                 scatter_gather_tensors=False):
    """
    Adapted from megatron.p2p_communication.
    Communicate tensors between stages. Used as helper method in other
    communication methods that are used in pipeline schedule.
    Takes the following arguments:
        tensor_send_next: tensor to send to next rank (no tensor sent if
                          set to None).
        tensor_send_prev: tensor to send to prev rank (no tensor sent if
                          set to None).
        recv_prev: boolean for whether tensor should be received from
                   previous rank.
        recv_next: boolean for whether tensor should be received from
                   next rank.
    Returns:
        (tensor_recv_prev, tensor_recv_next)
    """

    # Create placeholder tensors for receive in forward and backward directions
    # if needed.
    tensor_recv_prev = None
    tensor_recv_next = None

    if recv_prev:
        assert recv_prev_shape is not None
        recv_prev_chunk_shape, recv_prev_split = _get_tensor_shape(recv_prev_shape, scatter_gather_tensors)
        tensor_recv_prev = torch.empty(recv_prev_chunk_shape,
                                       requires_grad=True,
                                       device=get_current_device(),
                                       dtype=dtype)
    if recv_next:
        assert recv_next_shape is not None
        recv_next_chunk_shape, recv_next_split = _get_tensor_shape(recv_next_shape, scatter_gather_tensors)
        tensor_recv_next = torch.empty(recv_next_chunk_shape,
                                       requires_grad=True,
                                       device=get_current_device(),
                                       dtype=dtype)

    if tensor_send_prev is not None or recv_prev:
        if prev_rank is None:
            prev_rank = gpc.get_prev_global_rank(
                ParallelMode.PIPELINE)

    if tensor_send_next is not None or recv_next:
        if next_rank is None:
            next_rank = gpc.get_next_global_rank(
                ParallelMode.PIPELINE)

    if tensor_send_prev is not None:
        send_prev_split = _get_tensor_shape(tensor_send_prev.shape, scatter_gather_tensors)[1]
        if send_prev_split:
            tensor_send_prev = split_tensor_into_1d_equal_chunks(tensor_send_prev)

    if tensor_send_next is not None:
        send_next_split = _get_tensor_shape(tensor_send_next.shape, scatter_gather_tensors)[1]
        if send_next_split:
            tensor_send_next = split_tensor_into_1d_equal_chunks(tensor_send_next)

    ops = []
    if tensor_send_prev is not None:
        send_prev_op = dist.P2POp(dist.isend, tensor_send_prev, prev_rank)
        ops.append(send_prev_op)
    if tensor_recv_prev is not None:
        recv_prev_op = dist.P2POp(dist.irecv, tensor_recv_prev, prev_rank)
        ops.append(recv_prev_op)
    if tensor_recv_next is not None:
        recv_next_op = dist.P2POp(dist.irecv, tensor_recv_next, next_rank)
        ops.append(recv_next_op)
    if tensor_send_next is not None:
        send_next_op = dist.P2POp(dist.isend, tensor_send_next, next_rank)
        ops.append(send_next_op)
    if len(ops) > 0:
        reqs = dist.batch_isend_irecv(ops)
        for req in reqs:
            req.wait()
    # To protect against race condition when using batch_isend_irecv().
    torch.cuda.synchronize()

    if recv_prev and recv_prev_split:
        tensor_recv_prev = gather_split_1d_tensor(tensor_recv_prev).view(recv_prev_shape).requires_grad_()
    if recv_next and recv_next_split:
        tensor_recv_next = gather_split_1d_tensor(tensor_recv_next).view(recv_next_shape).requires_grad_()
    return tensor_recv_prev, tensor_recv_next


def recv_forward(input_tensor_shape, prev_rank=None, dtype=torch.float, scatter_gather_tensors=False):
    """Receives the input tensor from the previous member in pipeline.

    :param input_tensor_shape: The shape of the tensor to be recieved
    :param prev_rank: The rank of the source of the tensor
    :type input_tensor_shape: torch.Size
    :type prev_rank: int, optional
    :return: The input tensor in forward step
    :rtype: :class:`torch.Tensor`
    """
    if gpc.is_pipeline_first_stage():
        input_tensor = None
    else:
        input_tensor, _ = _communicate(recv_prev=True,
                                       recv_prev_shape=input_tensor_shape,
                                       prev_rank=prev_rank,
                                       dtype=dtype,
                                       scatter_gather_tensors=scatter_gather_tensors)
    return input_tensor


def recv_backward(output_grad_shape, next_rank=None, dtype=torch.float, scatter_gather_tensors=False):
    """Receives the grad tensor from the next member in pipeline.

    :param output_grad_shape: The shape of the tensor to be recieved
    :param next_rank: The rank of the source of the tensor
    :type output_grad_shape: torch.Size
    :type next_rank: int, optional
    :return: The grad of output tensor in forward step
    :rtype: :class:`torch.Tensor`
    """
    if gpc.is_pipeline_last_stage():
        output_tensor_grad = None
    else:
        _, output_tensor_grad = _communicate(recv_next=True,
                                             recv_next_shape=output_grad_shape,
                                             next_rank=next_rank,
                                             dtype=dtype,
                                             scatter_gather_tensors=scatter_gather_tensors)
    return output_tensor_grad


def send_forward(output_tensor, next_rank=None, scatter_gather_tensors=False):
    """Sends the input tensor to the next member in pipeline.

    :param output_tensor: Tensor to be sent
    :param next_rank: The rank of the recipient of the tensor
    :type output_tensor: :class:`torch.Tensor`
    :type next_rank: int, optional
    """
    if not gpc.is_pipeline_last_stage():
        _communicate(tensor_send_next=output_tensor,
                     next_rank=next_rank,
                     scatter_gather_tensors=scatter_gather_tensors)


def send_backward(input_tensor_grad, prev_rank=None, scatter_gather_tensors=False):
    """Sends the grad tensor to the previous member in pipeline.

    :param input_tensor_grad: Tensor to be sent
    :param prev_rank: The rank of the recipient of the tensor
    :type input_tensor_grad: :class:`torch.Tensor`
    :type prev_rank: int, optional
    """
    if not gpc.is_pipeline_first_stage():
        _communicate(tensor_send_prev=input_tensor_grad,
                     prev_rank=prev_rank,
                     scatter_gather_tensors=scatter_gather_tensors)


def send_forward_recv_backward(output_tensor,
                               output_grad_shape,
                               recv_next=True,
                               next_rank=None,
                               dtype=torch.float,
                               scatter_gather_tensors=False):
    """Batched communication operation. Sends the input tensor to the 
    next member in pipeline, while recieves the grad tensor from the
    next member in pipeline.

    :param output_tensor: Tensor to be sent
    :param output_grad_shape: The shape of the tensor to be recieved
    :type output_tensor: :class:`torch.Tensor`
    :type output_grad_shape: :class:`torch.Size`
    :return: The grad of output tensor in forward step
    :rtype: :class:`torch.Tensor`
    """
    if gpc.is_pipeline_last_stage():
        output_tensor_grad = None
    else:
        _, output_tensor_grad = _communicate(tensor_send_next=output_tensor,
                                             recv_next=recv_next,
                                             recv_next_shape=output_grad_shape,
                                             next_rank=next_rank,
                                             dtype=dtype,
                                             scatter_gather_tensors=scatter_gather_tensors)
    return output_tensor_grad


def send_backward_recv_forward(input_tensor_grad,
                               input_tensor_shape,
                               recv_prev=True,
                               prev_rank=None,
                               dtype=torch.float,
                               scatter_gather_tensors=False):
    """Batched communication operation. Sends the grad tensor to the 
    previous member in pipeline, while recieves the input tensor from the
    previous member in pipeline.

    :param input_tensor_grad: Tensor to be sent
    :param input_tensor_shape: The shape of the tensor to be recieved
    :type input_tensor_grad: :class:`torch.Tensor`
    :type input_tensor_shape: :class:`torch.Size`
    :return: The input tensor in forward step
    :rtype: :class:`torch.Tensor`
    """
    if gpc.is_pipeline_first_stage():
        input_tensor = None
    else:
        input_tensor, _ = _communicate(tensor_send_prev=input_tensor_grad,
                                       recv_prev=recv_prev,
                                       recv_prev_shape=input_tensor_shape,
                                       prev_rank=prev_rank,
                                       dtype=dtype,
                                       scatter_gather_tensors=scatter_gather_tensors)
    return input_tensor


def send_forward_recv_forward(output_tensor,
                              input_tensor_shape,
                              recv_prev=True,
                              prev_rank=None,
                              next_rank=None,
                              dtype=torch.float,
                              scatter_gather_tensors=False):
    """Batched communication operation. Sends the input tensor to the 
    next member in pipeline, while recieves the input tensor from the
    previous member in pipeline.

    :param output_tensor: Tensor to be sent
    :param input_tensor_shape: The shape of the tensor to be recieved
    :type output_tensor: :class:`torch.Tensor`
    :type input_tensor_shape: :class:`torch.Size`
    :return: The input tensor in forward step
    :rtype: :class:`torch.Tensor`
    """
    input_tensor, _ = _communicate(tensor_send_next=output_tensor,
                                   recv_prev=recv_prev,
                                   recv_prev_shape=input_tensor_shape,
                                   prev_rank=prev_rank,
                                   next_rank=next_rank,
                                   dtype=dtype,
                                   scatter_gather_tensors=scatter_gather_tensors)
    return input_tensor


def send_backward_recv_backward(input_tensor_grad,
                                output_grad_shape,
                                recv_next=True,
                                prev_rank=None,
                                next_rank=None,
                                dtype=torch.float,
                                scatter_gather_tensors=False):
    """Batched communication operation. Sends the grad tensor to the 
    previous member in pipeline, while recieves the grad tensor from the
    next member in pipeline.

    :param input_tensor_grad: Tensor to be sent
    :param output_grad_shape: The shape of the tensor to be recieved
    :type input_tensor_grad: :class:`torch.Tensor`
    :type output_grad_shape: :class:`torch.Size`
    :return: The grad of output tensor in forward step
    :rtype: :class:`torch.Tensor`
    """
    _, output_tensor_grad = _communicate(tensor_send_prev=input_tensor_grad,
                                         recv_next=recv_next,
                                         recv_next_shape=output_grad_shape,
                                         prev_rank=prev_rank,
                                         next_rank=next_rank,
                                         dtype=dtype,
                                         scatter_gather_tensors=scatter_gather_tensors)
    return output_tensor_grad


def send_forward_backward_recv_forward_backward(output_tensor,
                                                input_tensor_grad,
                                                input_tensor_shape,
                                                output_grad_shape,
                                                recv_prev=True,
                                                recv_next=True,
                                                prev_rank=None,
                                                next_rank=None,
                                                dtype=torch.float,
                                                scatter_gather_tensors=False):
    """Batched communication operation. Sends the input tensor to the next and 
    the grad tensor to the previous, while recieves the grad tensor from the
    next and the input tensor from the previous.

    :param output_tensor: Tensor sent to the next
    :param input_tensor_grad: Tensor sent to the previous
    :param input_tensor_shape: The shape of the tensor recieved from the previous
    :param output_grad_shape: The shape of the tensor recieved from the next
    :type output_tensor: :class:`torch.Tensor`
    :type input_tensor_grad: :class:`torch.Tensor`
    :type input_tensor_shape: :class:`torch.Size`
    :type output_grad_shape: :class:`torch.Size`
    :return: (the input tensor in forward step, the grad of output tensor in forward step)
    :rtype: (Tensor, Tensor)
    """
    input_tensor, output_tensor_grad = _communicate(
        tensor_send_next=output_tensor,
        tensor_send_prev=input_tensor_grad,
        recv_prev=recv_prev,
        recv_next=recv_next,
        recv_prev_shape=input_tensor_shape,
        recv_next_shape=output_grad_shape,
        prev_rank=prev_rank,
        next_rank=next_rank,
        dtype=dtype,
        scatter_gather_tensors=scatter_gather_tensors)
    return input_tensor, output_tensor_grad
