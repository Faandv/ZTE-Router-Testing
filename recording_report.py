"""Derived cable-marker attribution. Stored observations are never rewritten."""
from copy import deepcopy

LOOKBACK_SECONDS = 5
METHOD = ('An interruption still in progress that began up to 5 seconds before a marker '
          'is associated with that marker by timing, not proven causation. Older ongoing '
          'interruptions and interruptions spanning another marker are inconclusive. '
          'First response and three-sample stable recovery are separate measurements.')


def derive_recording(s, rows):
    result = deepcopy(s)
    markers = result.get('markers', [])
    result['recorded_markers'] = deepcopy(markers)
    result['recorded_outages'] = deepcopy(result.get('outages', []))
    result['attribution_method'] = METHOD
    result['attribution_version'] = 1
    transient = ('first_failure', 'first_recovered', 'recovered', 'marker_to_recovery',
                 'last_sample', 'timing_unreliable', 'observations', 'observation_text')
    for m in markers:
        for key in transient: m.pop(key, None)
        m.update(status='watching', timing_unreliable=False, observations=[])
    outages = result.get('outages', []) + ([result['outage']] if result.get('outage') else [])
    for o in outages:
        failure = o['first_failure']
        recovery = o.get('recovered', float('inf'))
        # Prefer a nearby later click while the interruption is still unconfirmed.
        later = [m for m in markers if failure < m['t'] <= failure + LOOKBACK_SECONDS
                 and m['t'] < recovery]
        prior = [m for m in markers if m['t'] <= failure]
        m = min(later, key=lambda m:m['t']) if later else (prior[-1] if prior else None)
        if m is None: continue
        following = next((n['t'] for n in markers if n['t'] > m['t']), float('inf'))
        observation = deepcopy(o)
        observation['pre_marker'] = failure < m['t']
        observation['crosses_marker'] = following != float('inf') and recovery >= following
        window_start = min(failure, m['t'])
        window_end = min(recovery, following, result.get('elapsed', result.get('duration', float('inf'))))
        relevant = [p for p in rows if p['t'] >= window_start and p.get('probe_start',p['t']) <= window_end]
        gaps = any(b['t']-a['t'] > 5 or abs((b['at']-a['at'])-(b['t']-a['t'])) > 3
                   for a,b in zip(relevant,relevant[1:]))
        contaminated = any(p.get('loaded') for p in relevant)
        observation['timing_unreliable'] = gaps or contaminated or observation['crosses_marker']
        o['associated_marker'] = m['id']
        o['association'] = 'nearby subsequent click' if observation['pre_marker'] else 'within marker window'
        o['report_phase'] = f"M{m['id']} - {m['label']} (timing association)"
        m['observations'].append(observation)
    for m in markers:
        items = m['observations']
        if not items:
            old = any(o['first_failure'] < m['t']-LOOKBACK_SECONDS and o.get('recovered',float('inf')) > m['t'] for o in outages)
            m['observation_text'] = ('Older interruption already in progress; no cable-specific timing' if old else
                'No associated interruption observed' if m.get('closed') or s['status']!='running' else 'Watching for interruptions')
            continue
        descriptions = []
        for o in items:
            prefix = (f"Interruption began {m['t']-o['first_failure']:.3f}s before click; "
                      if o['pre_marker'] else '')
            if o['timing_unreliable']:
                text = 'Timing inconclusive: load, monitoring gap, or another cable marker before stable recovery'
            elif 'recovered' not in o:
                text = 'Interruption observed; stable recovery not recorded'
            elif o.get('first_recovered',o['recovered']) < m['t']:
                text = f"First healthy response preceded click; stable recovery confirmed {o['recovered']-m['t']:.3f}s after click"
            else:
                text = (f"First healthy response {o.get('first_recovered',o['recovered'])-m['t']:.3f}s; "
                        f"stable recovery {o['recovered']-m['t']:.3f}s after click")
            descriptions.append(prefix + text)
        m['observation_text'] = ' | '.join(descriptions)
        first = items[0]
        m['first_failure'] = first['first_failure']
        m['timing_unreliable'] = any(o['timing_unreliable'] for o in items)
        if 'recovered' in first and not first['timing_unreliable']:
            m.update(recovered=first['recovered'],first_recovered=first.get('first_recovered'),
                     marker_to_recovery=round(first['recovered']-m['t'],3),status='recovered')
    return result
