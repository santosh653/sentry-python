import pytest
import gc

from sentry_sdk import Hub, start_span, start_transaction
from sentry_sdk.tracing import Span, Transaction
from sentry_sdk.tracing_utils import has_tracestate_enabled


def test_span_trimming(sentry_init, capture_events):
    sentry_init(traces_sample_rate=1.0, _experiments={"max_spans": 3})
    events = capture_events()

    with start_transaction(name="hi"):
        for i in range(10):
            with start_span(op="foo{}".format(i)):
                pass

    (event,) = events

    # the transaction is its own first span (which counts for max_spans) but it
    # doesn't show up in the span list in the event, so this is 1 less than our
    # max_spans value
    assert len(event["spans"]) == 2

    span1, span2 = event["spans"]
    assert span1["op"] == "foo0"
    assert span2["op"] == "foo1"


def test_transaction_naming(sentry_init, capture_events):
    sentry_init(traces_sample_rate=1.0)
    events = capture_events()

    # only transactions have names - spans don't
    with pytest.raises(TypeError):
        start_span(name="foo")
    assert len(events) == 0

    # default name in event if no name is passed
    with start_transaction() as transaction:
        pass
    assert len(events) == 1
    assert events[0]["transaction"] == "<unlabeled transaction>"

    # the name can be set once the transaction's already started
    with start_transaction() as transaction:
        transaction.name = "name-known-after-transaction-started"
    assert len(events) == 2
    assert events[1]["transaction"] == "name-known-after-transaction-started"

    # passing in a name works, too
    with start_transaction(name="a"):
        pass
    assert len(events) == 3
    assert events[2]["transaction"] == "a"


def test_start_transaction(sentry_init):
    sentry_init(traces_sample_rate=1.0)

    # you can have it start a transaction for you
    result1 = start_transaction(
        name="/interactions/other-dogs/new-dog", op="greeting.sniff"
    )
    assert isinstance(result1, Transaction)
    assert result1.name == "/interactions/other-dogs/new-dog"
    assert result1.op == "greeting.sniff"

    # or you can pass it an already-created transaction
    preexisting_transaction = Transaction(
        name="/interactions/other-dogs/new-dog", op="greeting.sniff"
    )
    result2 = start_transaction(preexisting_transaction)
    assert result2 is preexisting_transaction


def test_finds_transaction_on_scope(sentry_init):
    sentry_init(traces_sample_rate=1.0)

    transaction = start_transaction(name="dogpark")

    scope = Hub.current.scope

    # See note in Scope class re: getters and setters of the `transaction`
    # property. For the moment, assigning to scope.transaction merely sets the
    # transaction name, rather than putting the transaction on the scope, so we
    # have to assign to _span directly.
    scope._span = transaction

    # Reading scope.property, however, does what you'd expect, and returns the
    # transaction on the scope.
    assert scope.transaction is not None
    assert isinstance(scope.transaction, Transaction)
    assert scope.transaction.name == "dogpark"

    # If the transaction is also set as the span on the scope, it can be found
    # by accessing _span, too.
    assert scope._span is not None
    assert isinstance(scope._span, Transaction)
    assert scope._span.name == "dogpark"


def test_finds_transaction_when_descendent_span_is_on_scope(
    sentry_init,
):
    sentry_init(traces_sample_rate=1.0)

    transaction = start_transaction(name="dogpark")
    child_span = transaction.start_child(op="sniffing")

    scope = Hub.current.scope
    scope._span = child_span

    # this is the same whether it's the transaction itself or one of its
    # decedents directly attached to the scope
    assert scope.transaction is not None
    assert isinstance(scope.transaction, Transaction)
    assert scope.transaction.name == "dogpark"

    # here we see that it is in fact the span on the scope, rather than the
    # transaction itself
    assert scope._span is not None
    assert isinstance(scope._span, Span)
    assert scope._span.op == "sniffing"


def test_finds_orphan_span_on_scope(sentry_init):
    # this is deprecated behavior which may be removed at some point (along with
    # the start_span function)
    sentry_init(traces_sample_rate=1.0)

    span = start_span(op="sniffing")

    scope = Hub.current.scope
    scope._span = span

    assert scope._span is not None
    assert isinstance(scope._span, Span)
    assert scope._span.op == "sniffing"


def test_finds_non_orphan_span_on_scope(sentry_init):
    sentry_init(traces_sample_rate=1.0)

    transaction = start_transaction(name="dogpark")
    child_span = transaction.start_child(op="sniffing")

    scope = Hub.current.scope
    scope._span = child_span

    assert scope._span is not None
    assert isinstance(scope._span, Span)
    assert scope._span.op == "sniffing"


# TODO: We have a circular reference somewhere in how we store transactions and
# spans. This test was originally written to validate setting
# `span._containing_transaction = None` for all of a transaction's spans, but it
# fails on commits even before `_containing_transaction` was introduced. (Try
# checking out 874a46799ff771c5406e5d03fa962c2e835ce1bc and adding this test,
# with all of the debug printing (which is currently commented out) commented
# in. You'll see that even in the absence of `_containing_transaction`, calling
# `transaction.finish` leads to there being 30 things which need garbage
# collecting.)
@pytest.mark.xfail
def test_circular_references(sentry_init, request):

    # print("initial gc.garbage:", gc.garbage)

    # print("\n(top of function) collecting...")
    # num_collected = gc.collect()
    # print("number of items collected:", num_collected)
    # if num_collected > 0:
    #     print("gc.garbage after collection:", gc.garbage)

    # gc.set_debug(gc.DEBUG_LEAK)

    gc.collect()  # if debugging, comment this out in favor of the `num_collected` line above
    gc.disable()
    request.addfinalizer(gc.enable)

    sentry_init(traces_sample_rate=1.0)

    dogpark_transaction = start_transaction(name="dogpark")

    # at some point, you have to stop sniffing - there are balls to chase! - so
    # this span will end while the "dogpark" transaction is still open
    sniffing_span = dogpark_transaction.start_child(op="sniffing")
    # the wagging, however, continues long past the dogpark, so this span will
    # not finish before the transaction ends
    wagging_span = dogpark_transaction.start_child(op="wagging")

    sniffing_span.finish()

    # print("\n(about to finish transaction) collecting...")
    # num_collected = gc.collect()
    # print("number of items collected:", num_collected)
    # if num_collected > 0:
    #     print("gc.garbage after collection:", gc.garbage)

    dogpark_transaction.finish()

    # print("\n(just finished transaction, about to delete transaction) collecting...")
    # num_collected = gc.collect()
    # print("number of items collected:", num_collected)
    # if num_collected > 0:
    #     print("gc.garbage after collection:", gc.garbage)

    del dogpark_transaction

    # print("\n(just deleted transaction) collecting...")
    # num_collected = gc.collect()
    # print("number of items collected:", num_collected)
    # if num_collected > 0:
    #     print("gc.garbage after collection:", gc.garbage)

    wagging_span.finish()

    # print("\n(finished dangling span) collecting...")
    # num_collected = gc.collect()
    # print("number of items collected:", num_collected)
    # if num_collected > 0:
    #     print("gc.garbage after collection:", gc.garbage)

    assert gc.collect() == 0


# TODO (kmclb) remove this test once tracestate is a real feature
@pytest.mark.parametrize("tracestate_enabled", [True, False, None])
def test_has_tracestate_enabled(sentry_init, tracestate_enabled):
    experiments = (
        {"propagate_tracestate": tracestate_enabled}
        if tracestate_enabled is not None
        else {}
    )
    sentry_init(_experiments=experiments)

    if tracestate_enabled is True:
        assert has_tracestate_enabled() is True
    else:
        assert has_tracestate_enabled() is False
