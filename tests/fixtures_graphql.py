"""REAL GraphQL responses captured from GitHub 2026-07-28.

Roster handles are anonymized to insiderNN (hotinai is public, the roster is
not); every other byte -- error types, `path` arrays, null edges, field
shapes -- is exactly what GitHub returned. These are not hand-written guesses.

Two normalizations, and only two: logins are anonymized, and where edges were
trimmed for size, `hasNextPage` is set False to match (the trim is ours, not
GitHub's, and leaving it True would assert a truncation that never happened).

RESOURCE_LIMITS is the important one. It was produced at 40 users x 20 stars,
reproducibly (5/5), and it is HTTP 200 with rateLimit cost 1 and every user
present in `data`. The damage is inside: nulled edges where `starredAt` was
stripped. This is the likeliest way a fictional board ships.
"""

CLEAN_REQUESTED = ['insider00', 'insider01', 'insider02']
CLEAN = {'data': {'u0': {'login': 'insider00',
                 'starredRepositories': {'pageInfo': {'hasNextPage': False},
                                         'edges': [{'starredAt': '2026-03-13T21:01:20Z',
                                                    'node': {'nameWithOwner': 'hjanuschka/pi-multi-pass',
                                                             'createdAt': '2026-03-13T10:41:44Z',
                                                             'stargazerCount': 459,
                                                             'description': 'Multi-subscription '
                                                                            'extension '
                                                                            'for pi -- '
                                                                            'use '
                                                                            'multiple '
                                                                            'OAuth '
                                                                            'accounts '
                                                                            'per '
                                                                            'provider '
                                                                            '(Anthropic, '
                                                                            'Codex, '
                                                                            'Copilot, '
                                                                            'Gemini, '
                                                                            'Antigravity)'}},
                                                   {'starredAt': '2026-02-13T22:57:45Z',
                                                    'node': {'nameWithOwner': 'moonshine-ai/moonshine',
                                                             'createdAt': '2024-10-04T22:10:28Z',
                                                             'stargazerCount': 10502,
                                                             'description': 'Very low '
                                                                            'latency '
                                                                            'speech to '
                                                                            'text, '
                                                                            'intent '
                                                                            'recognition, '
                                                                            'and text '
                                                                            'to '
                                                                            'speech, '
                                                                            'for '
                                                                            'building '
                                                                            'voice '
                                                                            'agents '
                                                                            'and '
                                                                            'interfaces'}},
                                                   {'starredAt': '2026-02-13T18:28:27Z',
                                                    'node': {'nameWithOwner': 'basecamp/omarchy',
                                                             'createdAt': '2025-06-01T07:26:22Z',
                                                             'stargazerCount': 24154,
                                                             'description': 'Beautiful, '
                                                                            'Modern & '
                                                                            'Opinionated '
                                                                            'Linux'}}]}},
          'u1': {'login': 'insider01',
                 'starredRepositories': {'pageInfo': {'hasNextPage': False},
                                         'edges': [{'starredAt': '2019-02-24T06:53:34Z',
                                                    'node': {'nameWithOwner': 'jhessig/metric-gcode-truncator',
                                                             'createdAt': '2014-03-10T16:34:58Z',
                                                             'stargazerCount': 4,
                                                             'description': 'Modify '
                                                                            'metric '
                                                                            'MakerCam '
                                                                            'Gcode for '
                                                                            'use with '
                                                                            'grbl '
                                                                            'CNC'}},
                                                   {'starredAt': '2015-02-07T18:36:54Z',
                                                    'node': {'nameWithOwner': 'kaishengtai/torch-ntm',
                                                             'createdAt': '2015-02-05T05:53:27Z',
                                                             'stargazerCount': 278,
                                                             'description': 'A Neural '
                                                                            'Turing '
                                                                            'Machine '
                                                                            'implementation '
                                                                            'in '
                                                                            'Torch.'}},
                                                   {'starredAt': '2015-01-18T04:20:38Z',
                                                    'node': {'nameWithOwner': 'torch/torch7',
                                                             'createdAt': '2013-10-18T12:13:58Z',
                                                             'stargazerCount': 9140,
                                                             'description': 'http://torch.ch'}}]}},
          'u2': {'login': 'insider02',
                 'starredRepositories': {'pageInfo': {'hasNextPage': False},
                                         'edges': [{'starredAt': '2024-05-08T14:06:38Z',
                                                    'node': {'nameWithOwner': 'google-deepmind/torax',
                                                             'createdAt': '2024-03-05T14:20:02Z',
                                                             'stargazerCount': 700,
                                                             'description': 'TORAX: '
                                                                            'Tokamak '
                                                                            'transport '
                                                                            'simulation '
                                                                            'in JAX'}},
                                                   {'starredAt': '2017-04-20T16:46:07Z',
                                                    'node': {'nameWithOwner': 'Theano/Theano',
                                                             'createdAt': '2011-08-10T03:48:06Z',
                                                             'stargazerCount': 9997,
                                                             'description': 'Theano '
                                                                            'was a '
                                                                            'Python '
                                                                            'library '
                                                                            'that '
                                                                            'allows '
                                                                            'you to '
                                                                            'define, '
                                                                            'optimize, '
                                                                            'and '
                                                                            'evaluate '
                                                                            'mathematical '
                                                                            'expressions '
                                                                            'involving '
                                                                            'multi-dimensional '
                                                                            'arrays '
                                                                            'efficiently. '
                                                                            'It is '
                                                                            'being '
                                                                            'continued '
                                                                            'as '
                                                                            'PyTensor: '
                                                                            'www.github.com/pymc-devs/pytensor'}},
                                                   {'starredAt': '2012-02-03T18:26:06Z',
                                                    'node': {'nameWithOwner': 'insider02/TheanoLinear',
                                                             'createdAt': '2012-02-03T18:26:06Z',
                                                             'stargazerCount': 15,
                                                             'description': None}}]}},
          'rateLimit': {'cost': 1,
                        'remaining': 4999,
                        'resetAt': '2026-07-28T15:45:43Z'}}}

RESOURCE_LIMITS_REQUESTED = ['insider00', 'insider01', 'insider02', 'insider03']
RESOURCE_LIMITS = {'data': {'u0': {'login': 'insider00',
                 'starredRepositories': {'pageInfo': {'hasNextPage': False},
                                         'edges': [None, None, None]}},
          'u1': {'login': 'insider01',
                 'starredRepositories': {'pageInfo': {'hasNextPage': False},
                                         'edges': [None, None, None]}},
          'u2': {'login': 'insider02',
                 'starredRepositories': {'pageInfo': {'hasNextPage': False},
                                         'edges': [None, None, None]}},
          'u3': {'login': 'insider03',
                 'starredRepositories': {'pageInfo': {'hasNextPage': False},
                                         'edges': [None, None]}},
          'rateLimit': {'cost': 1,
                        'remaining': 4998,
                        'resetAt': '2026-07-28T15:45:43Z'}},
 'errors': [{'type': 'RESOURCE_LIMITS_EXCEEDED',
             'path': ['u0', 'starredRepositories', 'edges', 0, 'starredAt'],
             'locations': [{'line': 4, 'column': 15}],
             'message': 'Resource limits for this query exceeded.'},
            {'type': 'RESOURCE_LIMITS_EXCEEDED',
             'path': ['u0', 'starredRepositories', 'edges', 1, 'starredAt'],
             'locations': [{'line': 4, 'column': 15}],
             'message': 'Resource limits for this query exceeded.'},
            {'type': 'RESOURCE_LIMITS_EXCEEDED',
             'path': ['u0', 'starredRepositories', 'edges', 2, 'starredAt'],
             'locations': [{'line': 4, 'column': 15}],
             'message': 'Resource limits for this query exceeded.'},
            {'type': 'RESOURCE_LIMITS_EXCEEDED',
             'path': ['u1', 'starredRepositories', 'edges', 0, 'starredAt'],
             'locations': [{'line': 7, 'column': 15}],
             'message': 'Resource limits for this query exceeded.'},
            {'type': 'RESOURCE_LIMITS_EXCEEDED',
             'path': ['u1', 'starredRepositories', 'edges', 1, 'starredAt'],
             'locations': [{'line': 7, 'column': 15}],
             'message': 'Resource limits for this query exceeded.'},
            {'type': 'RESOURCE_LIMITS_EXCEEDED',
             'path': ['u1', 'starredRepositories', 'edges', 2, 'starredAt'],
             'locations': [{'line': 7, 'column': 15}],
             'message': 'Resource limits for this query exceeded.'},
            {'type': 'RESOURCE_LIMITS_EXCEEDED',
             'path': ['u2', 'starredRepositories', 'edges', 0, 'starredAt'],
             'locations': [{'line': 10, 'column': 15}],
             'message': 'Resource limits for this query exceeded.'},
            {'type': 'RESOURCE_LIMITS_EXCEEDED',
             'path': ['u2', 'starredRepositories', 'edges', 1, 'starredAt'],
             'locations': [{'line': 10, 'column': 15}],
             'message': 'Resource limits for this query exceeded.'},
            {'type': 'RESOURCE_LIMITS_EXCEEDED',
             'path': ['u2', 'starredRepositories', 'edges', 2, 'starredAt'],
             'locations': [{'line': 10, 'column': 15}],
             'message': 'Resource limits for this query exceeded.'},
            {'type': 'RESOURCE_LIMITS_EXCEEDED',
             'path': ['u3', 'starredRepositories', 'edges', 0, 'starredAt'],
             'locations': [{'line': 13, 'column': 15}],
             'message': 'Resource limits for this query exceeded.'},
            {'type': 'RESOURCE_LIMITS_EXCEEDED',
             'path': ['u3', 'starredRepositories', 'edges', 1, 'starredAt'],
             'locations': [{'line': 13, 'column': 15}],
             'message': 'Resource limits for this query exceeded.'}]}

NULL_USER_REQUESTED = ['ghost-account']
NULL_USER = {'data': {'u0': None,
          'rateLimit': {'cost': 1,
                        'remaining': 4997,
                        'resetAt': '2026-07-28T15:45:43Z'}},
 'errors': [{'type': 'NOT_FOUND',
             'path': ['u0'],
             'locations': [{'line': 2, 'column': 1}],
             'message': 'Could not resolve to a User with the login of '
                        "'this-account-does-not-exist-hotin-probe-x7'."}]}
