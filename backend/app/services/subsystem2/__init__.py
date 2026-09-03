"""Unit 20 (MEADOWOPS-API-004, DD-2): where Subsystem 2's own future
service-layer business logic lives (the AI-driven scenario/evaluation
engine, Phase 3 - genuinely empty scaffold today, since that logic doesn't
exist yet and Blocker B3's Claude API key is still absent). This is the
concrete namespace tests/architecture/test_subsystem_boundary.py polices:
nothing under `app.services.subsystem2` may import `app.db.session` or any
`live`-schema ORM model to read Subsystem 1's data directly (PRD 376,
S1-FR-6) - it must go through `request.app.state.subsystem2_client`
(app.core.internal_client) instead, the same way a real external caller
would. Freely importing this package's own `engine`-schema ORM models
(app.db.scenario, and any future Evaluation/Portfolio tables) is not
restricted by this rule - those are Subsystem 2's own data, not Subsystem
1's.
"""
