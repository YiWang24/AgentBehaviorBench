"""Accept independently validated Case artifacts without losing successful slots."""

import time
from dataclasses import replace
from types import MappingProxyType
from agentbench.harness.result import CaseResult


def accept_preparation(scheduler, state, job, outcome):
    """Apply a worker's complete or partial preparation on the coordinator thread."""
    if outcome.error is not None:
        state.preparation_error = outcome.error
        if not scheduler.continue_on_error:
            scheduler.admission = False
        for index in job.case_indices or tuple(state.identities):
            if index not in state.results:
                result = CaseResult(job.registration.agent_id, index, state.identities[index]['job_id'], 'skipped',
                                    error_type='CaseSkipped', error_message='Case batch preparation failed')
                state.results[index] = result
                scheduler._publish_case(state, result)
        return
    # Capture the entire accepted batch identity before any consumer can fail.
    for case in outcome.cases:
        state.identities[case.case_index] = MappingProxyType({**state.identities[case.case_index], 'case_id': case.case_id})
    for case in outcome.cases:
        case = scheduler.retain_case(job.registration.agent_id, case)
        state.prepared[case.case_index] = case
        state.pending.append(case)
        identity = MappingProxyType({**state.identities[case.case_index], 'case_id': case.case_id})
        state.identities[case.case_index] = identity
        scheduler._publish({**identity, 'event': 'case_prepared', 'prepared_case': case, 'status': 'prepared'})
        scheduler._publish({**identity, 'event': 'case_queued', 'status': 'queued'})
    if state.pending and state not in scheduler.ready:
        scheduler.ready.append(state)
    for failure in outcome.failures:
        identity = state.identities[failure.case_index]
        artifacts = dict(failure.artifacts or {})
        artifacts.update(phase=failure.phase, sdk_error={
            'code': failure.code, 'retryable': failure.retryable,
            'client_request_id': failure.client_request_id, 'request_id': failure.request_id})
        result = CaseResult(job.registration.agent_id, failure.case_index, identity['job_id'], 'failed',
                            error_type=failure.error_type, error_message=failure.error_message, artifacts=artifacts)
        if _retry_preparation(scheduler, state, result, artifacts):
            continue
        state.results[result.case_index] = result
        scheduler._publish_case(state, result)
        if (artifacts.get('recovery') or {}).get('pause_preparation') is True:
            pause_pending_preparation(scheduler, job.registration.agent_id, failure.code)
    requeue_unprepared(scheduler, state)
    for index in outcome.unattempted_indices:
        result = CaseResult(job.registration.agent_id, index, state.identities[index]['job_id'], 'skipped',
                            error_type='CasePreparationBlocked', error_message='Case generation was not attempted')
        state.results[index] = result
        scheduler._publish_case(state, result)
    if (outcome.failures or outcome.unattempted_indices) and not scheduler.continue_on_error:
        scheduler.admission = False


def pause_pending_preparation(scheduler, source_agent_id, code):
    """Pause undispatched preparation sharing this Suite's SDK configuration.

    Already accepted Cases can finish. In-flight preparation owns its own
    cleanup and partial outcomes; the coordinator only removes queued work.
    """
    while scheduler.unprepared:
        state = scheduler.unprepared.popleft()
        state.started = True
        for index in state.preparation.case_indices or tuple(state.identities):
            if index in state.results or index in state.prepared:
                continue
            identity = state.identities[index]
            result = CaseResult(state.preparation.registration.agent_id, index, identity['job_id'], 'skipped',
                error_type='CasePreparationPaused', error_message='Shared SDK configuration blocked new Case generation',
                artifacts={'phase': 'case_generation', 'blocked_by': {'agent_id': source_agent_id, 'code': code},
                           'recovery': {'action': 'generate_case', 'automatic': False}})
            state.results[index] = result
            scheduler._publish_case(state, result)
        scheduler._finish_agent(state)


def _retry_preparation(scheduler, state, result, artifacts) -> bool:
    """Charge one preparation attempt against the Case retry budget.

    Generation failures never reached ``RetryPolicy`` at all: ``_accept`` consults it
    only on the execution branch, so a slot whose request outcome is merely unknown was
    recorded as terminal on its first attempt. Leaving the slot out of ``state.results``
    is what lets ``requeue_unprepared`` pick it up again.
    """
    recovery = artifacts.get('recovery') or {}
    index = result.case_index
    retries = state.retries.get(index, 0)
    if not (scheduler.continue_on_error and scheduler.admission
            and recovery.get('automatic') is True
            and recovery.get('action') == 'replay_case'
            and retries < scheduler.retry_policy.max_retries):
        return False
    state.retries[index] = retries + 1
    delay = scheduler.retry_policy.delay(state.retries[index])
    scheduler._publish({**state.identities[index], 'event': 'case_attempt_failed',
                        'status': 'failed', 'case_result': result})
    scheduler._publish({**state.identities[index], 'event': 'retry_scheduled', 'status': 'retry_wait',
                        'retry_count': state.retries[index], 'retry_at': time.time() + delay,
                        'recovery_action': recovery['action']})
    return True


def requeue_unprepared(scheduler, state) -> None:
    """Re-dispatch preparation for slots that are neither prepared nor concluded."""
    missing = tuple(index for index in state.identities
                    if index not in state.prepared and index not in state.results)
    if not missing or state in scheduler.unprepared:
        return
    state.preparation = replace(state.preparation, case_indices=missing)
    scheduler.unprepared.append(state)
