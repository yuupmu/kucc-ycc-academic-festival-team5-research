
_RESOURCES = ('seats', 'laptops', 'projectors')
_FIELDS = {
    'reserve': frozenset(('event_id', 'op', 'reservation_id', 'user_id', 'needs', 'priority')),
    'cancel': frozenset(('event_id', 'op', 'reservation_id')),
    'amend': frozenset(('event_id', 'op', 'reservation_id', 'needs', 'priority')),
    'set_capacity': frozenset(('event_id', 'op', 'resource', 'capacity')),
}


def _signature(value):
    if isinstance(value, dict):
        return ('object', tuple(sorted((k, _signature(v)) for k, v in value.items())))
    if isinstance(value, list):
        return ('array', tuple(_signature(v) for v in value))
    if value is None:
        return ('null',)
    if type(value) is bool:
        return ('boolean', value)
    if type(value) is int:
        return ('integer', value)
    if type(value) is float:
        return ('float', value)
    if isinstance(value, str):
        return ('string', value)
    raise TypeError('JSON 입력만 지원한다')


def _valid_event(event):
    if not isinstance(event, dict):
        return False
    op = event.get('op')
    if not isinstance(op, str) or op not in _FIELDS:
        return False
    if set(event) != _FIELDS[op]:
        return False
    for field in ('event_id', 'reservation_id', 'user_id'):
        if field in event and not (isinstance(event[field], str) and event[field]):
            return False
    if op in ('reserve', 'amend'):
        needs = event['needs']
        if not isinstance(needs, dict) or 'seats' not in needs:
            return False
        if any(k not in _RESOURCES or type(v) is not int or v < 1
               for k, v in needs.items()):
            return False
        if type(event['priority']) is not int or not 0 <= event['priority'] <= 3:
            return False
    if op == 'set_capacity':
        if not isinstance(event['resource'], str) or event['resource'] not in _RESOURCES:
            return False
        if type(event['capacity']) is not int or event['capacity'] < 0:
            return False
    return True


def _available(capacities, reservations):
    available = dict(capacities)
    for reservation in reservations.values():
        if reservation['status'] == 'confirmed':
            for resource, quantity in reservation['needs'].items():
                available[resource] -= quantity
    return available


def _waiting(reservations):
    return sorted((r for r in reservations.values() if r['status'] == 'waiting'),
                  key=lambda r: (-r['priority'], r['order']))


def _state_error(event, capacities, reservations):
    op = event['op']
    if op == 'reserve':
        if event['reservation_id'] in reservations:
            return 'duplicate_reservation'
        if any(r['user_id'] == event['user_id'] and r['status'] != 'cancelled'
               for r in reservations.values()):
            return 'duplicate_user'
    elif op in ('cancel', 'amend'):
        target = reservations.get(event['reservation_id'])
        if target is None:
            return 'unknown_reservation'
        if target['status'] == 'cancelled':
            return 'not_active'
        if op == 'amend' and target['status'] == 'confirmed':
            available = _available(capacities, reservations)
            if any(quantity > available[resource] + target['needs'].get(resource, 0)
                   for resource, quantity in event['needs'].items()):
                return 'insufficient_capacity'
    elif op == 'set_capacity':
        resource = event['resource']
        available = _available(capacities, reservations)
        if event['capacity'] < capacities[resource] - available[resource]:
            return 'capacity_below_usage'
    return None


def _allocate(capacities, reservations, event_id, notifications):
    available = _available(capacities, reservations)
    admitted = []
    for reservation in _waiting(reservations):
        if all(quantity <= available[resource]
               for resource, quantity in reservation['needs'].items()):
            for resource, quantity in reservation['needs'].items():
                available[resource] -= quantity
            reservation['status'] = 'confirmed'
            reservation_id = reservation['reservation_id']
            admitted.append(reservation_id)
            notifications.append({'event_id': event_id, 'type': 'confirmed',
                                  'reservation_id': reservation_id})
    return admitted


def simulate(initial_state: dict, events: list[dict]) -> dict:
    """확정 정책을 처리한다. 성공한 set_capacity의 code는 인간 답변 대기다."""
    capacities = {r: initial_state['capacities'][r] for r in _RESOURCES}
    reservations = {}
    results = []
    notifications = []
    cache = {}
    for position, event in enumerate(events, 1):
        # 모든 사건에 유효한 문자열 event_id가 존재한다는 입력 보장.
        event_id = event['event_id']
        signature = _signature(event)
        if event_id in cache:
            first_signature, first_code = cache[event_id]
            replayed = signature == first_signature
            results.append({'event_id': event_id,
                            'code': first_code if replayed else 'event_id_conflict',
                            'replayed': replayed, 'admitted': []})
            continue

        code = 'invalid_event' if not _valid_event(event) else _state_error(
            event, capacities, reservations)
        admitted = []
        if code is None:
            op = event['op']
            if op == 'set_capacity':
                raise NotImplementedError(
                    '인간 판단 대기: capacity_success_code '
                    '(d4df95e766814192a17ebd2feff2c192). '
                    '성공한 set_capacity의 code가 아직 확정되지 않았습니다.')
            reservation_id = event['reservation_id']
            if op == 'reserve':
                reservations[reservation_id] = {
                    'reservation_id': reservation_id,
                    'user_id': event['user_id'],
                    'needs': dict(event['needs']),
                    'priority': event['priority'],
                    'status': 'waiting',
                    'order': position,
                }
            elif op == 'cancel':
                reservations[reservation_id]['status'] = 'cancelled'
                notifications.append({'event_id': event_id, 'type': 'cancelled',
                                      'reservation_id': reservation_id})
                code = 'cancelled'
            else:
                target = reservations[reservation_id]
                target['needs'] = dict(event['needs'])
                target['priority'] = event['priority']
                code = 'amended'
            admitted = _allocate(capacities, reservations, event_id, notifications)
            if op == 'reserve':
                code = ('confirmed' if reservations[reservation_id]['status'] == 'confirmed'
                        else 'queued')
        cache[event_id] = (signature, code)
        results.append({'event_id': event_id, 'code': code,
                        'replayed': False, 'admitted': admitted})

    return {
        'event_results': results,
        'final_state': {
            'capacities': capacities,
            'available': _available(capacities, reservations),
            'reservations': [reservations[k] for k in sorted(reservations)],
            'waitlist': [r['reservation_id'] for r in _waiting(reservations)],
        },
        'notifications': notifications,
    }
