"""
Monitor System for VPU Simulator

Tracks everything in the simulator using spans (distributed tracing model).
All trackable things (instructions, waiting items, messages, cache requests) are spans
that have a start time, end time, and parent/child relationships.

See PLAN_MONITOR.md for design details and use cases.
"""
import json
import logging
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Dict, List, Any, Tuple

logger = logging.getLogger(__name__)


class CompletionType(Enum):
    """How a span completes."""
    TRACKED = 'TRACKED'                 # Creator knows when done (has real completed_cycle)
    FIRE_AND_FORGET = 'FIRE_AND_FORGET' # Creator dispatched but doesn't wait; check children


class SpanType(Enum):
    """Types of spans in the trace."""
    RISCV_INSTR = 'RISCV_INSTR'      # A RISC-V instruction being executed
    KINSTR = 'KINSTR'                # A kamlet-level instruction (Load, Store, etc.)
    KINSTR_EXEC = 'KINSTR_EXEC'      # A kinstr executing on a specific kamlet
    WITEM = 'WITEM'                  # A waiting item tracking async work
    MESSAGE = 'MESSAGE'              # A message sent between components
    CACHE_REQUEST = 'CACHE_REQUEST'  # A cache line request to memory
    SETUP = 'SETUP'                  # Initialization/setup phase span
    FLOW_CONTROL = 'FLOW_CONTROL'    # Flow control span (e.g., ident query)
    TRANSACTION = 'TRANSACTION'      # Sub-transaction (e.g., WriteMemWord)
    RESOURCE_EXHAUSTED = 'RESOURCE_EXHAUSTED'  # Resource table full
    SYNC = 'SYNC'                    # Global synchronization operation across kamlets
    SYNC_LOCAL = 'SYNC_LOCAL'        # Local sync participation at a synchronizer


class ResourceType(Enum):
    """Types of resources that can be exhausted."""
    WITEM_TABLE = 'WITEM_TABLE'              # Witem slots in a kamlet
    CACHE_REQUEST_TABLE = 'CACHE_REQUEST_TABLE'  # Cache request slots in a kamlet
    INSTR_IDENT = 'INSTR_IDENT'              # Instruction identifiers in lamlet
    INSTR_BUFFER_TOKENS = 'INSTR_BUFFER_TOKENS'  # Instruction buffer tokens per kamlet


@dataclass
class SpanRef:
    """A reference to another span."""
    span_id: int
    reason: str


@dataclass
class Event:
    """A timestamped event within a span."""
    cycle: int
    event: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Span:
    """A span in the distributed trace."""
    span_id: int
    span_type: SpanType
    created_cycle: int
    completion_type: CompletionType
    completed_cycle: int | None = None
    parent: SpanRef | None = None
    children: List[SpanRef] = field(default_factory=list)
    depends_on: List[SpanRef] = field(default_factory=list)
    component: str = ""  # "lamlet", "kamlet(0,0)", "jamlet(1,2)"
    details: Dict[str, Any] = field(default_factory=dict)
    events: List[Event] = field(default_factory=list)
    # For FIRE_AND_FORGET spans: True once all children have been created
    children_finalized: bool = False

    def is_complete(self) -> bool:
        return self.completed_cycle is not None


class Monitor:
    """
    Central monitoring system for the VPU simulator.

    Uses spans (distributed tracing model) where everything (RISC-V instructions,
    kinstructions, waiting items, cache requests, messages) is tracked with
    parent/child and depends_on relationships.
    """

    def __init__(self, clock, params, enabled: bool = True):
        self.clock = clock
        self.params = params
        self.enabled = enabled

        # Span storage
        self.spans: Dict[int, Span] = {}
        self._next_span_id: int = 0

        # Lookup tables: derive span_id from existing identifiers
        self._kinstr_by_ident: Dict[int, int] = {}  # instr_ident -> span_id
        # kinstr_exec key: (instr_ident, kamlet_x, kamlet_y) -> span_id
        self._kinstr_exec_by_key: Dict[tuple, int] = {}
        # witem key: (instr_ident, kamlet_x, kamlet_y) -> span_id
        self._witem_by_key: Dict[tuple, int] = {}
        # transaction key: (ident, tag, src_x, src_y, dst_x, dst_y) -> span_id
        self._transaction_by_key: Dict[tuple, int] = {}
        # message key: (ident, tag, src_x, src_y, dst_x, dst_y) -> span_id
        self._message_by_key: Dict[tuple, int] = {}
        # cache_request key: (kamlet_x, kamlet_y, slot) -> span_id
        self._cache_request_by_key: Dict[tuple, int] = {}
        # resource_exhausted key: (ResourceType, kamlet_x, kamlet_y) -> span_id
        self._resource_exhausted_by_key: Dict[tuple, int] = {}
        # sync key: (sync_ident, name) -> span_id (name distinguishes first/second sync)
        self._sync_by_key: Dict[tuple, int] = {}
        # sync_local key: (sync_ident, x, y) -> span_id
        self._sync_local_by_key: Dict[tuple, int] = {}

        # Input queue stats per jamlet: (x, y) -> {ch0_ready, ch0_consumed, ch1andup_ready, ch1andup_consumed}
        self._input_queue_stats: Dict[tuple, Dict[str, int]] = {}

        # Send queue stats per jamlet per message type:
        # (x, y, message_type_name) -> {attempts, blocked_cycles}
        self._send_queue_stats: Dict[tuple, Dict[str, int]] = {}

    # -------------------------------------------------------------------------
    # Core Span methods
    # -------------------------------------------------------------------------

    def create_span(self, span_type: SpanType, component: str, completion_type: CompletionType,
                    parent_span_id: int | None = None, parent_reason: str = '',
                    **details) -> int | None:
        """Create a new span. Returns the span_id."""
        if not self.enabled:
            return None

        span_id = self._next_span_id
        self._next_span_id += 1

        parent_ref = None
        if parent_span_id is not None:
            parent_ref = SpanRef(span_id=parent_span_id, reason=parent_reason)
            # Add this span as a child of the parent
            parent_span = self.spans.get(parent_span_id)
            assert parent_span is not None, f"Parent span {parent_span_id} not found"
            if parent_span.children_finalized:
                hierarchy = self.format_span_tree(parent_span_id)
                assert False, \
                    f"Cannot add child to parent {parent_span_id} ({parent_span.span_type.name}) - " \
                    f"children already finalized.\n\nParent hierarchy:\n{hierarchy}"
            parent_span.children.append(SpanRef(span_id=span_id, reason=parent_reason))

        span = Span(
            span_id=span_id,
            span_type=span_type,
            created_cycle=self.clock.cycle,
            completion_type=completion_type,
            parent=parent_ref,
            component=component,
            details=details,
        )
        self.spans[span_id] = span
        return span_id

    def complete_span(self, span_id: int, skip_children_check: bool = False) -> None:
        """Mark a span as complete.

        After completing, checks if parent is FIRE_AND_FORGET and all siblings
        are complete - if so, completes the parent too (recursively).

        Args:
            span_id: The span to complete.
            skip_children_check: If True, don't require children to be complete first.
                Used for instructions like IdentQuery where the lamlet completes the
                kinstr when it receives the response, even though kinstr_exec spans
                may still be running.
        """
        if not self.enabled:
            return
        assert span_id is not None
        span = self.spans.get(span_id)
        assert span is not None, f"Span {span_id} not found"
        assert span.completed_cycle is None, f"Span {span_id} already completed"

        # Verify all children are complete before completing this span
        if not skip_children_check:
            for child_ref in span.children:
                child_span = self.spans.get(child_ref.span_id)
                assert child_span is not None, \
                    f"Child span {child_ref.span_id} not found when completing span {span_id}"
                if not child_span.is_complete():
                    hierarchy = self.format_span_tree(span_id)
                    assert False, \
                        f"Cannot complete span {span_id} ({span.span_type.value}): " \
                        f"child {child_ref.span_id} ({child_span.span_type.value}) is not complete. " \
                        f"Child details: {child_span.details}\n\nSpan hierarchy:\n{hierarchy}"

        # Verify all dependencies are complete before completing this span
        for dep_ref in span.depends_on:
            dep_span = self.spans.get(dep_ref.span_id)
            assert dep_span is not None, \
                f"Dependency span {dep_ref.span_id} not found when completing span {span_id}"
            assert dep_span.is_complete(), \
                f"Cannot complete span {span_id} ({span.span_type.value}): " \
                f"dependency {dep_ref.span_id} ({dep_span.span_type.value}) is not complete. " \
                f"Dependency reason: {dep_ref.reason}, details: {dep_span.details}"

        span.completed_cycle = self.clock.cycle

        # Clean up lookup tables based on span type
        if span.span_type == SpanType.KINSTR:
            instr_ident = span.details.get("instr_ident")
            if instr_ident is not None:
                self._kinstr_by_ident.pop(instr_ident, None)
        elif span.span_type == SpanType.KINSTR_EXEC:
            instr_ident = span.details.get("instr_ident")
            kamlet_x = span.details.get("kamlet_x")
            kamlet_y = span.details.get("kamlet_y")
            key = (instr_ident, kamlet_x, kamlet_y)
            self._kinstr_exec_by_key.pop(key, None)

        # Check if parent should be auto-completed
        if span.parent:
            parent = self.spans.get(span.parent.span_id)
            if parent and parent.completion_type == CompletionType.FIRE_AND_FORGET:
                if not parent.is_complete() and parent.children_finalized:
                    all_children_complete = all(
                        self.spans.get(child.span_id) and self.spans[child.span_id].is_complete()
                        for child in parent.children
                    )
                    if all_children_complete:
                        self.complete_span(parent.span_id)  # Recursive

    def finalize_children(self, span_id: int) -> None:
        """Mark that all children have been created for a FIRE_AND_FORGET span.

        This must be called before auto-completion can trigger.
        If all children are already complete, this will trigger auto-completion.
        """
        if not self.enabled:
            return
        span = self.spans.get(span_id)
        assert span is not None, f"Span {span_id} not found"
        assert span.completion_type == CompletionType.FIRE_AND_FORGET, \
            f"finalize_children only valid for FIRE_AND_FORGET spans"
        assert not span.children_finalized, f"Span {span_id} children already finalized"
        span.children_finalized = True

        # Check if we can auto-complete now
        if not span.is_complete():
            all_children_complete = all(
                self.spans.get(child.span_id) and self.spans[child.span_id].is_complete()
                for child in span.children
            )
            if all_children_complete:
                self.complete_span(span_id)

    def add_event(self, span_id: int, event: str, **kwargs) -> None:
        """Add a timestamped event to a span."""
        if not self.enabled or span_id is None:
            return
        span = self.spans.get(span_id)
        if span is None:
            return
        span.events.append(Event(cycle=self.clock.cycle, event=event, details=kwargs))

    def add_dependency(self, span_id: int, depends_on_span_id: int, reason: str) -> None:
        """Add a dependency from one span to another."""
        if not self.enabled:
            return
        assert span_id is not None
        assert depends_on_span_id is not None
        span = self.spans.get(span_id)
        assert span is not None, f"Span {span_id} not found"
        depends_on_span = self.spans.get(depends_on_span_id)
        assert depends_on_span is not None, f"Depends-on span {depends_on_span_id} not found"
        span.depends_on.append(SpanRef(span_id=depends_on_span_id, reason=reason))

    def get_span(self, span_id: int) -> Span | None:
        """Get a span by ID."""
        return self.spans.get(span_id)

    def record_kinstr_created(self, kinstr, parent_span_id: int) -> int:
        """Record a kinstr creation. Delegates to kinstr.create_span()."""
        span_id = kinstr.create_span(self, parent_span_id)
        # Store in lookup table if kinstr has an instr_ident
        if kinstr.instr_ident is not None:
            assert kinstr.instr_ident not in self._kinstr_by_ident, \
                f"instr_ident {kinstr.instr_ident} already in lookup table"
            self._kinstr_by_ident[kinstr.instr_ident] = span_id
        return span_id

    def get_kinstr_span_id(self, instr_ident: int) -> int | None:
        """Look up the span_id for a kinstr by its instr_ident."""
        return self._kinstr_by_ident.get(instr_ident)

    def get_kinstr_dispatch_cycle(self, instr_ident: int) -> int | None:
        """Get the cycle when a kinstr was dispatched (sent to kamlets).

        Returns None if not yet dispatched.
        """
        span_id = self._kinstr_by_ident[instr_ident]
        span = self.spans[span_id]
        dispatch_events = [e for e in span.events if e.event == "dispatched"]
        assert len(dispatch_events) <= 1
        if dispatch_events:
            return dispatch_events[0].cycle
        return None

    def complete_kinstr(self, instr_ident: int) -> None:
        """Complete a kinstr span by its instr_ident."""
        if not self.enabled:
            return
        span_id = self._kinstr_by_ident.get(instr_ident)
        assert span_id is not None, f"No kinstr span for instr_ident {instr_ident}"
        self.complete_span(span_id)

    def record_kinstr_exec_created(self, instr, kamlet_x: int, kamlet_y: int) -> int | None:
        """Record a kinstr_exec creation (kinstr executing on a specific kamlet)."""
        if not self.enabled:
            return None
        instr_ident = instr.instr_ident
        instr_type = type(instr).__name__
        key = (instr_ident, kamlet_x, kamlet_y)
        if key in self._kinstr_exec_by_key:
            existing_span_id = self._kinstr_exec_by_key[key]
            print(f"kinstr_exec key {key} already in lookup table")
            print(self.dump_span(existing_span_id))
            assert False, f"kinstr_exec key {key} already in lookup table"
        parent_span_id = self._kinstr_by_ident.get(instr_ident)
        if parent_span_id is None:
            raise KeyError(
                f"kinstr {instr_type} with instr_ident={instr_ident} not found in lookup table. "
                f"Was it already completed? Active idents: {list(self._kinstr_by_ident.keys())}"
            )
        span_id = self.create_span(
            span_type=SpanType.KINSTR_EXEC,
            component=f"kamlet({kamlet_x},{kamlet_y})",
            completion_type=CompletionType.FIRE_AND_FORGET,
            parent_span_id=parent_span_id,
            instr_ident=instr_ident,
            instr_type=instr_type,
            kamlet_x=kamlet_x,
            kamlet_y=kamlet_y,
        )
        self._kinstr_exec_by_key[key] = span_id
        return span_id

    def get_kinstr_exec_span_id(self, instr_ident: int, kamlet_x: int, kamlet_y: int) -> int | None:
        """Look up the span_id for a kinstr_exec by its key."""
        return self._kinstr_exec_by_key.get((instr_ident, kamlet_x, kamlet_y))

    def get_oldest_active_instr_ident(self) -> int | None:
        """Get the instr_ident of the oldest active kinstr.

        Returns None if no active kinstr have instr_idents.
        """
        assert self.enabled
        if not self._kinstr_by_ident:
            return None
        oldest_span_id = min(self._kinstr_by_ident.values())
        for ident, span_id in self._kinstr_by_ident.items():
            if span_id == oldest_span_id:
                return ident
        return None

    def dump_span(self, span_id: int) -> str:
        """Dump debug info about a Span and its children."""
        span = self.spans.get(span_id)
        if span is None:
            return f"span_id {span_id} not found"
        lines = [
            f"span_id={span_id} type={span.span_type.value}",
            f"  created={span.created_cycle} completed={span.completed_cycle}",
            f"  completion_type={span.completion_type.value}",
            f"  component={span.component}",
            f"  details={span.details}",
            f"  children ({len(span.children)}):",
        ]
        for child_ref in span.children:
            child = self.spans.get(child_ref.span_id)
            if child:
                lines.append(
                    f"    span_id={child_ref.span_id} type={child.span_type.value} "
                    f"completed={child.completed_cycle} details={child.details}"
                )
            else:
                lines.append(f"    span_id={child_ref.span_id} (not found)")
        return "\n".join(lines)

    def _witem_key(self, instr_ident: int, kamlet_x: int, kamlet_y: int,
                   source_x: int | None = None, source_y: int | None = None) -> tuple:
        """Create lookup key for a witem."""
        if source_x is not None:
            return (instr_ident, kamlet_x, kamlet_y, source_x, source_y)
        return (instr_ident, kamlet_x, kamlet_y)

    def record_witem_created(self, instr_ident: int, kamlet_x: int, kamlet_y: int,
                             witem_type: str, finalize: bool = True,
                             parent_span_id: int | None = None,
                             source_x: int | None = None,
                             source_y: int | None = None) -> int | None:
        """Record a witem creation.

        If finalize is True (default), also finalizes the parent's children.
        Set to False if more witems will be added to the same parent.

        parent_span_id: Explicit parent span. If None, looks up kinstr_exec by instr_ident.

        source_x, source_y: For witems that use source to match (e.g., WaitingWriteMemWord),
        include in the key.

        Returns the span_id of the created witem span, or None if monitoring disabled.
        """
        if not self.enabled:
            return None
        key = self._witem_key(instr_ident, kamlet_x, kamlet_y, source_x, source_y)
        if key in self._witem_by_key:
            existing_span_id = self._witem_by_key[key]
            existing_span = self.spans[existing_span_id]
            assert existing_span.parent is not None
            parent_id = existing_span.parent.span_id
            raise AssertionError(
                f"witem key {key} already in lookup table.\n\n"
                f"Existing span:\n{self.dump_span(existing_span_id)}\n\n"
                f"Existing span's parent:\n{self.dump_span(parent_id)}\n\n"
                f"New witem: type={witem_type}, "
                f"instr_ident={instr_ident}, kamlet=({kamlet_x},{kamlet_y}), "
                f"source=({source_x},{source_y}), parent_span_id={parent_span_id}"
            )
        if parent_span_id is None:
            parent_key = (instr_ident, kamlet_x, kamlet_y)
            parent_span_id = self._kinstr_exec_by_key.get(parent_key)
            if parent_span_id is None:
                raise KeyError(
                    f"kinstr_exec for {witem_type} not found: "
                    f"instr_ident={instr_ident}, kamlet=({kamlet_x},{kamlet_y}). "
                    f"Available keys for this ident: "
                    f"{[k for k in self._kinstr_exec_by_key if k[0] == instr_ident]}"
                )
        span_id = self.create_span(
            span_type=SpanType.WITEM,
            component=f"kamlet({kamlet_x},{kamlet_y})",
            completion_type=CompletionType.TRACKED,
            parent_span_id=parent_span_id,
            witem_type=witem_type,
            instr_ident=instr_ident,
        )
        self._witem_by_key[key] = span_id
        if finalize:
            self.finalize_children(parent_span_id)
        return span_id

    def get_witem_span_id(self, instr_ident: int, kamlet_x: int, kamlet_y: int,
                          source_x: int | None = None,
                          source_y: int | None = None) -> int | None:
        """Look up the span_id for a witem by its key."""
        if not self.enabled:
            return None
        key = self._witem_key(instr_ident, kamlet_x, kamlet_y, source_x, source_y)
        return self._witem_by_key.get(key)

    def complete_witem(self, instr_ident: int, kamlet_x: int, kamlet_y: int,
                       source_x: int | None = None,
                       source_y: int | None = None) -> None:
        """Complete a witem and remove from lookup table."""
        if not self.enabled:
            return
        key = self._witem_key(instr_ident, kamlet_x, kamlet_y, source_x, source_y)
        span_id = self._witem_by_key.pop(key, None)
        if span_id is not None:
            self.complete_span(span_id)

    def finalize_kinstr_exec(self, instr_ident: int, kamlet_x: int, kamlet_y: int) -> None:
        """Mark that all children have been created for a kinstr_exec."""
        if not self.enabled:
            return
        span_id = self._kinstr_exec_by_key[(instr_ident, kamlet_x, kamlet_y)]
        self.finalize_children(span_id)

    # -------------------------------------------------------------------------
    # Transaction tracking
    # -------------------------------------------------------------------------

    def _transaction_key(self, ident: int, tag: int | None,
                         src_x: int, src_y: int, dst_x: int, dst_y: int) -> tuple:
        """Create lookup key for a transaction."""
        return (ident, tag, src_x, src_y, dst_x, dst_y)

    def get_transaction_span_id(self, ident: int, tag: int | None,
                                src_x: int, src_y: int,
                                dst_x: int, dst_y: int) -> int | None:
        """Look up the span_id for a transaction by its key."""
        if not self.enabled:
            return None
        key = self._transaction_key(ident, tag, src_x, src_y, dst_x, dst_y)
        return self._transaction_by_key.get(key)

    def create_transaction(self, transaction_type: str, ident: int,
                           src_x: int, src_y: int, dst_x: int, dst_y: int,
                           parent_span_id: int,
                           tag: int | None = None) -> int | None:
        """Create a transaction span, or return existing one for resends.

        A transaction is a logical operation (e.g., WriteMemWord) that may involve
        request/response messages and work at the destination. For RETRY scenarios,
        the same transaction continues, so this returns the existing span_id.

        parent_span_id: The parent span (typically the witem that initiated this transaction).

        Returns the transaction span_id.
        """
        if not self.enabled:
            return None

        # Check if transaction already exists (for resends after RETRY)
        key = self._transaction_key(ident, tag, src_x, src_y, dst_x, dst_y)
        if key in self._transaction_by_key:
            return self._transaction_by_key[key]

        span_id = self.create_span(
            span_type=SpanType.TRANSACTION,
            component=f"jamlet({src_x},{src_y})",
            completion_type=CompletionType.TRACKED,
            parent_span_id=parent_span_id,
            transaction_type=transaction_type,
            ident=ident,
            tag=tag,
            src_x=src_x,
            src_y=src_y,
            dst_x=dst_x,
            dst_y=dst_y,
        )

        self._transaction_by_key[key] = span_id

        return span_id

    def _message_key(self, ident: int, tag: int | None,
                      src_x: int, src_y: int, dst_x: int, dst_y: int,
                      message_type: str) -> tuple:
        """Create lookup key for a message."""
        return (ident, tag, src_x, src_y, dst_x, dst_y, message_type)

    def record_message_sent(self, parent_span_id: int, message_type: str,
                            ident: int, tag: int | None,
                            src_x: int, src_y: int, dst_x: int, dst_y: int,
                            drop_reason: str | None = None) -> int | None:
        """Record a message being sent. Span stays open until received."""
        if not self.enabled:
            return None

        details = {'message_type': message_type}
        if drop_reason is not None:
            details['drop_reason'] = drop_reason

        span_id = self.create_span(
            span_type=SpanType.MESSAGE,
            component=f"jamlet({src_x},{src_y})",
            completion_type=CompletionType.TRACKED,
            parent_span_id=parent_span_id,
            **details,
        )

        key = self._message_key(ident, tag, src_x, src_y, dst_x, dst_y, message_type)
        self._message_by_key[key] = span_id
        return span_id

    def _tag_from_header(self, header: 'IdentHeader') -> int | None:
        """Extract tag from header."""
        if hasattr(header, 'address'):
            return header.address * self.params.j_in_k // self.params.cache_line_bytes
        elif hasattr(header, 'tag'):
            return header.tag
        else:
            return None

    def _message_key_from_header(self, header: 'IdentHeader',
                                  dst_x: int | None = None,
                                  dst_y: int | None = None) -> tuple:
        """Build message key from header.

        For broadcast messages, dst_x and dst_y must be passed explicitly.
        For non-broadcast messages, uses header.target_x/y (and asserts they match if passed).
        """
        from zamlet.message import SendType
        if header.send_type == SendType.BROADCAST:
            assert dst_x is not None and dst_y is not None, \
                "dst_x and dst_y must be passed for broadcast messages"
        else:
            if dst_x is not None or dst_y is not None:
                assert dst_x == header.target_x and dst_y == header.target_y, \
                    f"dst ({dst_x}, {dst_y}) doesn't match header target " \
                    f"({header.target_x}, {header.target_y})"
            dst_x = header.target_x
            dst_y = header.target_y
        tag = self._tag_from_header(header)
        return self._message_key(
            header.ident, tag,
            header.source_x, header.source_y,
            dst_x, dst_y,
            header.message_type.name)

    def get_message_span_id_by_header(self, header: 'IdentHeader',
                                       dst_x: int | None = None,
                                       dst_y: int | None = None) -> int | None:
        """Look up a message span_id by header.

        For broadcast messages, dst_x and dst_y must be passed explicitly.
        For non-broadcast messages, uses header.target_x/y (and asserts they match if passed).
        """
        if not self.enabled:
            return None
        key = self._message_key_from_header(header, dst_x, dst_y)
        return self._message_by_key.get(key)

    def record_message_received(self, ident: int, src_x: int, src_y: int,
                                 dst_x: int, dst_y: int,
                                 message_type: str = None) -> None:
        """Record a simple message (no tag) being received. Completes the MESSAGE span."""
        if not self.enabled:
            return
        key = self._message_key(ident, None, src_x, src_y, dst_x, dst_y, message_type)
        self._complete_message(key)

    def record_message_received_by_header(self, header,
                                          dst_x: int | None = None,
                                          dst_y: int | None = None) -> None:
        """Record a cache/tagged message being received. Completes the MESSAGE span.

        For broadcast messages, dst_x and dst_y must be passed explicitly.
        For non-broadcast messages, uses header.target_x/y (and asserts they match if passed).
        """
        if not self.enabled:
            return
        key = self._message_key_from_header(header, dst_x, dst_y)
        self._complete_message(key)

    def _complete_message(self, key: tuple) -> None:
        """Complete a message span by key."""
        logger.debug(f"{self.clock.cycle}: _complete_message: key={key}")
        span_id = self._message_by_key.pop(key, None)
        assert span_id is not None, \
            f"Message received but no span found for key={key}. " \
            f"Available keys: {list(self._message_by_key.keys())}"
        self.complete_span(span_id)

    def complete_transaction(self, ident: int, tag: int | None,
                              src_x: int, src_y: int, dst_x: int, dst_y: int) -> None:
        """Complete a transaction and remove from lookup table."""
        if not self.enabled:
            return

        key = self._transaction_key(ident, tag, src_x, src_y, dst_x, dst_y)
        span_id = self._transaction_by_key.pop(key, None)
        assert span_id is not None, f"Transaction not found: {key}"
        self.complete_span(span_id)

    def record_cache_write(self, span_id: int | None, sram_addr: int,
                           old_value: str, new_value: str) -> None:
        """Record data written to cache on a transaction span."""
        if not self.enabled or span_id is None:
            return
        span = self.spans[span_id]
        span.details['sram_addr'] = sram_addr
        span.details['old_value'] = old_value
        span.details['new_value'] = new_value

    # -------------------------------------------------------------------------
    # Cache request tracking
    # -------------------------------------------------------------------------

    def _cache_request_key(self, kamlet_x: int, kamlet_y: int, slot: int) -> tuple:
        """Create lookup key for a cache request."""
        return (kamlet_x, kamlet_y, slot)

    def get_cache_request_span_id(self, kamlet_x: int, kamlet_y: int, slot: int) -> int | None:
        """Look up the span_id for a cache request by its key."""
        if not self.enabled:
            return None
        key = self._cache_request_key(kamlet_x, kamlet_y, slot)
        return self._cache_request_by_key.get(key)

    def record_cache_request_created(self, kamlet_x: int, kamlet_y: int, slot: int,
                                      request_type: str, memory_loc: int,
                                      parent_span_id: int | None = None) -> int | None:
        """Record a cache request being created.

        parent_span_id: The witem span that triggered this cache request.
        """
        if not self.enabled:
            return None

        key = self._cache_request_key(kamlet_x, kamlet_y, slot)
        assert key not in self._cache_request_by_key, \
            f"Cache request key {key} already in lookup table"

        span_id = self.create_span(
            span_type=SpanType.CACHE_REQUEST,
            component=f"kamlet({kamlet_x},{kamlet_y})",
            completion_type=CompletionType.TRACKED,
            parent_span_id=parent_span_id,
            parent_reason="witem_triggered_cache_request",
            request_type=request_type,
            slot=slot,
            memory_loc=memory_loc,
        )

        self._cache_request_by_key[key] = span_id
        return span_id

    def record_cache_request_completed(self, kamlet_x: int, kamlet_y: int, slot: int) -> None:
        """Record a cache request completing."""
        if not self.enabled:
            return

        key = self._cache_request_key(kamlet_x, kamlet_y, slot)
        span_id = self._cache_request_by_key.pop(key, None)
        assert span_id is not None, \
            f"Cache request completed but no span found: kamlet({kamlet_x},{kamlet_y}) slot={slot}"
        self.complete_span(span_id)

    # -------------------------------------------------------------------------
    # Resource exhaustion tracking
    # -------------------------------------------------------------------------

    def _resource_exhausted_key(self, resource_type: ResourceType,
                                 kamlet_x: int | None, kamlet_y: int | None) -> tuple:
        """Create lookup key for a resource exhaustion span."""
        return (resource_type, kamlet_x, kamlet_y)

    def record_resource_exhausted(self, resource_type: ResourceType,
                                   kamlet_x: int | None, kamlet_y: int | None) -> int | None:
        """Record that a resource has become exhausted (e.g., witem table full).

        Creates a RESOURCE_EXHAUSTED span if one doesn't already exist.
        For lamlet-level resources, use kamlet_x=None, kamlet_y=None.
        Returns the span_id, or None if monitoring disabled or span already exists.
        """
        if not self.enabled:
            return None

        key = self._resource_exhausted_key(resource_type, kamlet_x, kamlet_y)
        if key in self._resource_exhausted_by_key:
            return self._resource_exhausted_by_key[key]

        if kamlet_x is None:
            component = "lamlet"
        else:
            component = f"kamlet({kamlet_x},{kamlet_y})"
        span_id = self.create_span(
            span_type=SpanType.RESOURCE_EXHAUSTED,
            component=component,
            completion_type=CompletionType.TRACKED,
            resource_type=resource_type.value,
        )

        self._resource_exhausted_by_key[key] = span_id
        return span_id

    def get_resource_exhausted_span_id(self, resource_type: ResourceType,
                                        kamlet_x: int | None, kamlet_y: int | None) -> int | None:
        """Get the span_id for an active resource exhaustion, or None if not exhausted."""
        if not self.enabled:
            return None
        key = self._resource_exhausted_key(resource_type, kamlet_x, kamlet_y)
        return self._resource_exhausted_by_key.get(key)

    def record_resource_available(self, resource_type: ResourceType,
                                   kamlet_x: int | None, kamlet_y: int | None) -> None:
        """Record that a resource has become available again.

        Completes the RESOURCE_EXHAUSTED span if one exists.
        """
        if not self.enabled:
            return

        key = self._resource_exhausted_key(resource_type, kamlet_x, kamlet_y)
        span_id = self._resource_exhausted_by_key.pop(key, None)
        if span_id is not None:
            self.complete_span(span_id)

    def record_witem_blocked_by_resource(self, witem_instr_ident: int,
                                          kamlet_x: int, kamlet_y: int,
                                          resource_type: ResourceType) -> None:
        """Record that a witem is blocked waiting for a resource.

        Adds a dependency from the witem span to the resource exhaustion span.
        """
        if not self.enabled:
            return

        witem_span_id = self.get_witem_span_id(witem_instr_ident, kamlet_x, kamlet_y)
        assert witem_span_id is not None, (
            f"witem span not found for instr_ident={witem_instr_ident} "
            f"kamlet=({kamlet_x},{kamlet_y})")
        resource_span_id = self.get_resource_exhausted_span_id(
            resource_type, kamlet_x, kamlet_y)
        assert resource_span_id is not None, (
            f"resource span not found for {resource_type.value} "
            f"kamlet=({kamlet_x},{kamlet_y})")
        self.add_dependency(
            witem_span_id, resource_span_id,
            f"blocked_by_{resource_type.value.lower()}")

    # -------------------------------------------------------------------------
    # Sync tracking
    # -------------------------------------------------------------------------

    def record_sync_created(self, sync_ident: int, parent_span_id: int,
                             name: str | None = None) -> int | None:
        """Record that a global sync operation has started.

        Creates a SYNC span as a child of the kinstr. Caller should create SYNC_LOCAL children.
        Returns the global span_id.
        """
        if not self.enabled:
            return None

        global_span_id = self.create_span(
            span_type=SpanType.SYNC,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            parent_span_id=parent_span_id,
            parent_reason="sync",
            sync_ident=sync_ident,
            sync_name=name,
        )
        self._sync_by_key[(sync_ident, name)] = global_span_id
        return global_span_id

    def record_sync_local_created(self, sync_ident: int, x: int, y: int,
                                   parent_span_id: int,
                                   name: str | None = None) -> int | None:
        """Record a local sync span for a synchronizer."""
        if not self.enabled:
            return None

        key = (sync_ident, x, y, name)
        local_span_id = self.create_span(
            span_type=SpanType.SYNC_LOCAL,
            component=f"synchronizer({x},{y})",
            completion_type=CompletionType.TRACKED,
            parent_span_id=parent_span_id,
            parent_reason="sync_participant",
            sync_ident=sync_ident,
        )
        self._sync_local_by_key[key] = local_span_id
        return local_span_id

    def finalize_sync_children(self, sync_ident: int, name: str | None = None) -> None:
        """Finalize children of the global sync span."""
        if not self.enabled:
            return
        global_span_id = self._sync_by_key.get((sync_ident, name))
        if global_span_id is not None:
            self.finalize_children(global_span_id)

    def create_sync_spans(self, sync_ident: int, parent_span_id: int, params,
                          name: str | None = None) -> None:
        """Create global SYNC span and SYNC_LOCAL children for all synchronizers.

        If spans already exist (created by another participant), does nothing.
        """
        if not self.enabled:
            return
        # Check if already created
        if (sync_ident, name) in self._sync_by_key:
            return
        global_span_id = self.record_sync_created(sync_ident, parent_span_id, name)
        for ky in range(params.k_rows):
            for kx in range(params.k_cols):
                self.record_sync_local_created(sync_ident, kx, ky, global_span_id, name)
        # Lamlet synchronizer at (0, -1)
        self.record_sync_local_created(sync_ident, 0, -1, global_span_id, name)
        self.finalize_sync_children(sync_ident, name)

    def _find_oldest_sync_local(self, sync_ident: int, x: int, y: int,
                                 completed: bool = False) -> tuple | None:
        """Find the oldest local sync span for this location.

        Args:
            completed: If False, find oldest incomplete. If True, find oldest completed.
        Returns:
            The key (sync_ident, x, y, name) or None if not found.
        """
        oldest_key = None
        oldest_cycle = float('inf')
        for key, span_id in self._sync_local_by_key.items():
            if key[0] == sync_ident and key[1] == x and key[2] == y:
                span = self.spans[span_id]
                is_complete = span.completed_cycle is not None
                if is_complete == completed and span.created_cycle < oldest_cycle:
                    oldest_cycle = span.created_cycle
                    oldest_key = key
        return oldest_key

    def record_sync_local_event(self, sync_ident: int, x: int, y: int,
                                 value: int | None = None) -> None:
        """Record that a synchronizer has seen its local event."""
        if not self.enabled:
            return

        key = self._find_oldest_sync_local(sync_ident, x, y, completed=False)
        assert key is not None, f"No incomplete sync local span for ({sync_ident}, {x}, {y})"
        span_id = self._sync_local_by_key[key]
        self.add_event(span_id, "local_event", value=value)

    def record_sync_local_complete(self, sync_ident: int, x: int, y: int,
                                     min_value: int | None) -> None:
        """Record that sync completed at a synchronizer."""
        if not self.enabled:
            return

        key = self._find_oldest_sync_local(sync_ident, x, y, completed=False)
        assert key is not None, f"No incomplete sync local span for ({sync_ident}, {x}, {y})"
        span_id = self._sync_local_by_key[key]
        self.spans[span_id].details['min_value'] = min_value
        self.complete_span(span_id)

        # If parent SYNC span is now complete, clean up its lookup entry
        parent_span_id = self.spans[span_id].parent.span_id
        if self.spans[parent_span_id].is_complete():
            for k, v in list(self._sync_by_key.items()):
                if v == parent_span_id:
                    del self._sync_by_key[k]
                    break

    def record_rf_blocking(self, instr_ident: int, kamlet_x: int, kamlet_y: int,
                           read_regs, write_regs, rf_info, waiting_items) -> None:
        """Record dependencies when an instruction is blocked waiting for register file.

        Finds which rf_ident tokens are blocking the requested registers, then records
        dependencies from the kinstr_exec span to the witems holding those tokens.
        """
        if not self.enabled:
            return
        if read_regs is None:
            read_regs = []
        if write_regs is None:
            write_regs = []
        blocked_span_id = self.get_kinstr_exec_span_id(instr_ident, kamlet_x, kamlet_y)
        assert blocked_span_id is not None, \
            f"kinstr_exec span not found for instr_ident={instr_ident}"
        blocking_tokens = set()
        for reg in read_regs:
            if not rf_info.can_read(reg):
                blocking_tokens.add(rf_info.write[reg])
        for reg in write_regs:
            if not rf_info.can_write(reg):
                if rf_info.write[reg] is not None:
                    blocking_tokens.add(rf_info.write[reg])
                for token in rf_info.reads[reg]:
                    blocking_tokens.add(token)
        for witem in waiting_items:
            if witem.rf_ident in blocking_tokens:
                blocking_span_id = self.get_witem_span_id(
                    witem.instr_ident, kamlet_x, kamlet_y)
                if blocking_span_id is not None:
                    self.add_dependency(blocked_span_id, blocking_span_id, "waiting_for_rf")

    def _get_input_queue_stats(self, x: int, y: int) -> Dict[str, int]:
        """Get or create input queue stats for a jamlet."""
        key = (x, y)
        if key not in self._input_queue_stats:
            self._input_queue_stats[key] = {
                'ch0_ready': 0, 'ch0_consumed': 0,
                'ch1andup_ready': 0, 'ch1andup_consumed': 0
            }
        return self._input_queue_stats[key]

    def record_input_queue_ready(self, x: int, y: int, is_ch0: bool) -> None:
        """Record that input queue has data ready this cycle."""
        if not self.enabled:
            return
        stats = self._get_input_queue_stats(x, y)
        if is_ch0:
            stats['ch0_ready'] += 1
        else:
            stats['ch1andup_ready'] += 1

    def record_input_queue_consumed(self, x: int, y: int, is_ch0: bool) -> None:
        """Record that data was consumed from input queue this cycle."""
        if not self.enabled:
            return
        stats = self._get_input_queue_stats(x, y)
        if is_ch0:
            stats['ch0_consumed'] += 1
        else:
            stats['ch1andup_consumed'] += 1

    def _get_send_queue_stats(self, x: int, y: int, message_type_name: str) -> Dict[str, int]:
        """Get or create send queue stats for a jamlet/message type."""
        key = (x, y, message_type_name)
        if key not in self._send_queue_stats:
            self._send_queue_stats[key] = {'total_cycles': 0, 'blocked_cycles': 0}
        return self._send_queue_stats[key]

    def record_send_queue_attempt(self, x: int, y: int, message_type_name: str,
                                   blocked_cycles: int) -> None:
        """Record a send queue attempt with how many cycles it was blocked."""
        if not self.enabled:
            return
        stats = self._get_send_queue_stats(x, y, message_type_name)
        stats['total_cycles'] += blocked_cycles + 1
        stats['blocked_cycles'] += blocked_cycles

    # -------------------------------------------------------------------------
    # Query methods
    # -------------------------------------------------------------------------

    def get_spans_by_type(self, span_type: SpanType) -> List[Span]:
        """Get all spans of a specific type."""
        return [span for span in self.spans.values() if span.span_type == span_type]

    def get_pending_spans(self, span_type: SpanType | None = None) -> List[Span]:
        """Get spans that haven't completed yet, optionally filtered by type."""
        spans = self.spans.values()
        if span_type is not None:
            spans = [s for s in spans if s.span_type == span_type]
        return [s for s in spans if not s.is_complete()]

    def get_completed_spans(self, span_type: SpanType | None = None) -> List[Span]:
        """Get spans that have completed, optionally filtered by type."""
        spans = self.spans.values()
        if span_type is not None:
            spans = [s for s in spans if s.span_type == span_type]
        return [s for s in spans if s.is_complete()]

    def get_span_tree(self, span_id: int) -> Dict[str, Any]:
        """Get a span and all its descendants as a tree structure."""
        span = self.spans.get(span_id)
        if span is None:
            return {}
        return self._build_tree(span)

    def _build_tree(self, span: Span) -> Dict[str, Any]:
        """Recursively build tree structure for a span."""
        children_trees = []
        for child_ref in span.children:
            child_span = self.spans.get(child_ref.span_id)
            if child_span:
                children_trees.append({
                    'reason': child_ref.reason,
                    'span': self._build_tree(child_span),
                })
        return {
            'span_id': span.span_id,
            'span_type': span.span_type.value,
            'component': span.component,
            'created_cycle': span.created_cycle,
            'completed_cycle': span.completed_cycle,
            'completion_type': span.completion_type.value,
            'details': span.details,
            'depends_on': [{'span_id': d.span_id, 'reason': d.reason} for d in span.depends_on],
            'children': children_trees,
        }

    def get_real_completion_cycle(self, span_id: int) -> int | None:
        """
        Get the actual completion cycle for a span.

        For TRACKED spans, this is the completed_cycle.
        For FIRE_AND_FORGET spans, this is the max completion cycle of all descendants.
        """
        span = self.spans.get(span_id)
        if span is None:
            return None

        if span.completion_type == CompletionType.TRACKED:
            return span.completed_cycle

        # FIRE_AND_FORGET - need to find max completion of all descendants
        return self._get_max_descendant_completion(span)

    def _get_max_descendant_completion(self, span: Span) -> int | None:
        """Get the maximum completion cycle among all descendants."""
        if not span.children:
            return span.completed_cycle

        max_cycle = span.completed_cycle
        for child_ref in span.children:
            child_span = self.spans.get(child_ref.span_id)
            if child_span is None:
                continue
            child_completion = self._get_max_descendant_completion(child_span)
            if child_completion is None:
                return None  # Still pending
            if max_cycle is None or child_completion > max_cycle:
                max_cycle = child_completion

        return max_cycle

    def get_spans_blocking_on(self, span_id: int) -> List[Span]:
        """Find all spans that depend on a specific span."""
        result = []
        for span in self.spans.values():
            for dep in span.depends_on:
                if dep.span_id == span_id:
                    result.append(span)
                    break
        return result

    # -------------------------------------------------------------------------
    # Statistics and analysis
    # -------------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Get summary statistics."""
        all_spans = list(self.spans.values())
        completed = [s for s in all_spans if s.is_complete()]
        pending = [s for s in all_spans if not s.is_complete()]

        # Group by type
        by_type: Dict[str, Dict[str, Any]] = {}
        for span in all_spans:
            type_name = span.span_type.value
            if type_name not in by_type:
                by_type[type_name] = {'total': 0, 'completed': 0, 'pending': 0, 'latencies': []}
            by_type[type_name]['total'] += 1
            if span.is_complete():
                by_type[type_name]['completed'] += 1
                latency = span.completed_cycle - span.created_cycle
                by_type[type_name]['latencies'].append(latency)
            else:
                by_type[type_name]['pending'] += 1

        # Calculate latency stats
        latency_stats = {}
        for span_type, data in by_type.items():
            latencies = data['latencies']
            latency_stats[span_type] = {
                'total': data['total'],
                'completed': data['completed'],
                'pending': data['pending'],
            }
            if latencies:
                latency_stats[span_type].update({
                    'avg_latency': sum(latencies) / len(latencies),
                    'max_latency': max(latencies),
                    'min_latency': min(latencies),
                })

        return {
            'total_cycles': self.clock.cycle,
            'total_spans': len(all_spans),
            'completed_spans': len(completed),
            'pending_spans': len(pending),
            'by_type': latency_stats,
        }

    def print_summary(self):
        """Print a formatted summary of the simulation."""
        stats = self.get_stats()

        print(f'\n{"="*70}')
        print(f'Simulation Summary ({stats["total_cycles"]} cycles)')
        print(f'{"="*70}')

        print(f'\nTotal spans: {stats["total_spans"]} '
              f'({stats["completed_spans"]} completed, {stats["pending_spans"]} pending)')

        print(f'\nBy Type:')
        print(f'  {"Type":<20} {"Total":<8} {"Done":<8} {"Pend":<8} '
              f'{"Avg":<10} {"Max":<10} {"Min":<10}')
        print(f'  {"-"*20} {"-"*8} {"-"*8} {"-"*8} {"-"*10} {"-"*10} {"-"*10}')
        for span_type, data in sorted(stats['by_type'].items()):
            avg = data.get('avg_latency', '-')
            max_lat = data.get('max_latency', '-')
            min_lat = data.get('min_latency', '-')
            if isinstance(avg, float):
                avg = f'{avg:.1f}'
            print(f'  {span_type:<20} {data["total"]:<8} {data["completed"]:<8} '
                  f'{data["pending"]:<8} {avg:<10} {max_lat:<10} {min_lat:<10}')

        # Show pending spans if any
        pending = self.get_pending_spans()
        if pending:
            print(f'\nPending spans ({len(pending)}):')
            for span in pending[:10]:  # Show first 10
                age = self.clock.cycle - span.created_cycle
                deps = ', '.join(f'{d.span_id}:{d.reason}' for d in span.depends_on)
                deps_str = f' depends_on=[{deps}]' if deps else ''
                print(f'  [{span.span_id}] {span.span_type.value} @ {span.component} '
                      f'(age={age}){deps_str}')
                if span.details:
                    details_str = ', '.join(f'{k}={v}' for k, v in span.details.items())
                    print(f'       {details_str}')
            if len(pending) > 10:
                print(f'  ... and {len(pending) - 10} more')

        # Show input queue utilization
        if self._input_queue_stats:
            print(f'\nInput queue utilization:')
            print(f'  {"Jamlet":<12} {"Ch0 Ready":<12} {"Ch0 Cons":<12} {"Ch0 %":<10} '
                  f'{"Ch1+ Ready":<12} {"Ch1+ Cons":<12} {"Ch1+ %":<10}')
            print(f'  {"-"*12} {"-"*12} {"-"*12} {"-"*10} {"-"*12} {"-"*12} {"-"*10}')
            for (x, y), s in sorted(self._input_queue_stats.items()):
                ch0_pct = (s['ch0_consumed'] / s['ch0_ready'] * 100) if s['ch0_ready'] > 0 else 0
                ch1_pct = (s['ch1andup_consumed'] / s['ch1andup_ready'] * 100) if s['ch1andup_ready'] > 0 else 0
                print(f'  ({x},{y})        {s["ch0_ready"]:<12} {s["ch0_consumed"]:<12} {ch0_pct:<10.1f} '
                      f'{s["ch1andup_ready"]:<12} {s["ch1andup_consumed"]:<12} {ch1_pct:<10.1f}')

        # Show send queue blocking stats
        if self._send_queue_stats:
            print(f'\nSend queue blocking:')
            print(f'  {"Jamlet":<10} {"Message Type":<30} {"Total":<10} {"Blocked":<10} '
                  f'{"Blocked %":<10}')
            print(f'  {"-"*10} {"-"*30} {"-"*10} {"-"*10} {"-"*10}')
            for (x, y, msg_type), s in sorted(self._send_queue_stats.items()):
                if s['total_cycles'] > 0:
                    blocked_pct = s['blocked_cycles'] / s['total_cycles'] * 100
                    print(f'  ({x},{y})      {msg_type:<30} {s["total_cycles"]:<10} '
                          f'{s["blocked_cycles"]:<10} {blocked_pct:<10.1f}')

        # Show hierarchical view of slowest RISCV_INSTR spans
        riscv_instrs = [s for s in self.spans.values()
                        if s.span_type == SpanType.RISCV_INSTR and s.is_complete()]
        if riscv_instrs:
            riscv_instrs.sort(key=lambda s: s.completed_cycle - s.created_cycle, reverse=True)
            print(f'\nSlowest instructions:')
            for span in riscv_instrs[:3]:
                self.print_span_tree(span.span_id)

    def get_pending_state(self) -> Dict[str, Any]:
        """Get current state of pending spans for deadlock analysis."""
        pending = self.get_pending_spans()

        pending_info = []
        for span in pending:
            deps = [{'span_id': d.span_id, 'reason': d.reason} for d in span.depends_on]
            pending_info.append({
                'span_id': span.span_id,
                'span_type': span.span_type.value,
                'component': span.component,
                'created_cycle': span.created_cycle,
                'age': self.clock.cycle - span.created_cycle,
                'depends_on': deps,
                'details': span.details,
            })

        return {
            'cycle': self.clock.cycle,
            'pending_spans': pending_info,
        }

    def dump_to_file(self, path: str):
        """Export all data to a JSON file."""
        def enum_encoder(obj):
            if isinstance(obj, Enum):
                return obj.name
            raise TypeError(f'Object of type {type(obj)} is not JSON serializable')

        data = {
            'stats': self.get_stats(),
            'spans': {span_id: asdict(span) for span_id, span in self.spans.items()},
        }

        with open(path, 'w') as f:
            json.dump(data, f, indent=2, default=enum_encoder)

    # -------------------------------------------------------------------------
    # Hierarchical display
    # -------------------------------------------------------------------------

    def format_span_tree(self, span_id: int, max_depth: int = 10) -> str:
        """Format a span and all its descendants as a tree string."""
        span = self.spans.get(span_id)
        if span is None:
            return f"No span found with id {span_id}"

        lines = []
        if span.is_complete():
            latency = span.completed_cycle - span.created_cycle
            lines.append(f"\nSpan {span_id} (latency={latency} cycles):")
        else:
            age = self.clock.cycle - span.created_cycle
            lines.append(f"\nSpan {span_id} (pending, age={age} cycles):")

        lines.append("-" * 70)
        self._format_span_tree_recursive(span, lines, indent=0, max_depth=max_depth)
        return '\n'.join(lines)

    def print_span_tree(self, span_id: int, max_depth: int = 10):
        """Print a span and all its descendants as a tree."""
        print(self.format_span_tree(span_id, max_depth))

    def _format_span_tree_recursive(self, span: Span, lines: list, indent: int, max_depth: int):
        """Recursively format span tree into lines."""
        if indent > max_depth:
            lines.append("  " * indent + "...")
            return

        prefix = "  " * indent
        if span.is_complete():
            duration = span.completed_cycle - span.created_cycle
            timing = f"{span.created_cycle}-{span.completed_cycle} ({duration})"
        else:
            age = self.clock.cycle - span.created_cycle
            timing = f"{span.created_cycle}-? (pending {age})"

        lines.append(f"{prefix}{span.span_type.value} @ {span.component} [{timing}]")

        # Show key details on same line or next
        if span.details:
            detail_items = [f"{k}={v}" for k, v in span.details.items()]
            if detail_items:
                lines.append(f"{prefix}  {', '.join(detail_items)}")

        # Show events
        for event in span.events:
            event_details = ', '.join(f"{k}={v}" for k, v in event.details.items())
            lines.append(f"{prefix}  @{event.cycle}: {event.event} {event_details}")

        # Format children sorted by start time
        children_spans = []
        for child_ref in span.children:
            child_span = self.spans.get(child_ref.span_id)
            if child_span:
                children_spans.append(child_span)
        children_spans.sort(key=lambda s: s.created_cycle)

        for child_span in children_spans:
            self._format_span_tree_recursive(child_span, lines, indent + 1, max_depth)

        # Format depends_on (not recursively - just show what this span waits on)
        if span.depends_on:
            for dep_ref in span.depends_on:
                dep_span = self.spans.get(dep_ref.span_id)
                if dep_span:
                    if dep_span.is_complete():
                        duration = dep_span.completed_cycle - dep_span.created_cycle
                        timing = f"{dep_span.created_cycle}-{dep_span.completed_cycle} ({duration})"
                    else:
                        age = self.clock.cycle - dep_span.created_cycle
                        timing = f"{dep_span.created_cycle}-? (pending {age})"
                    lines.append(f"{prefix}  waiting_for: {dep_span.span_type.value} @ {dep_span.component} [{timing}] ({dep_ref.reason})")
