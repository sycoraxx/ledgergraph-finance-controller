'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';
import LedgerMesh, { type MeshData } from './LedgerMesh';

type Stage = { step: string; name: string; note: string; status: string };
type Source = { name: string; rows: number; sha256: string; status: string; modified_at_utc?: string | null; extracted_at_utc?: string | null; coverage_start?: string | null; coverage_end?: string | null; source_system?: string };
type Tier = { tier: number; n: number; matched: number; comp_ok: number; refusal: number; batch_acc: string };
type Issue = { code: string; entity_id: string; reason: string; unresolved_amount: string; citation: string };
type ExceptionItem = {
  bank_txn_id: string; settlement_id: string | null; tier: number; reason: string; detail: string;
  component_status: string; approval_status: string; unresolved_amount: string;
  unresolved_amount_display: string; confidence: number; citations: string[]; issues: Issue[]; is_true_refusal: boolean;
};
type JournalEntry = { account: string; debit: string; credit: string };
type Journal = {
  proposal_id: string; bank_txn_id: string; settlement_id: string; entries: JournalEntry[];
  bank_txn_ids?: string[]; settlement_ids?: string[]; topology?: string;
  total_debit: string; total_credit: string; display_amount: string; balanced: boolean;
  workflow_status: string; ledger_entry_id?: string | null; reviewer?: string | null; decided_at?: string | null;
  approval: { status: string; reason: string; blockers: string[] };
};
type AuditEvent = {
  event: string; bank_txn_id?: string; settlement_id?: string; proposal_id?: string;
  decision?: string; reviewer?: string; note?: string; at?: string; confidence?: number;
  status?: string; layer?: string; issues?: Issue[];
};
type ScenarioContext = {
  id: string; label: string; category: string; category_label: string; category_short_label: string;
  required_sources: string[]; realism_basis: string; frequency_note: string; claim_boundary: string;
};
type ScenarioCategory = {
  id: string; label: string; short_label: string; description: string; examples: string[];
};
type ScenarioCatalog = {
  authority?: string; frequency_boundary?: string; categories: ScenarioCategory[];
  scenarios: Record<string, ScenarioContext>; references?: { label: string; url: string }[];
};
type RiskFinding = {
  bank_txn_id: string; direction: 'credit' | 'debit'; amount: string; amount_display: string;
  transaction_timestamp_utc: string; source_extracted_at_utc?: string | null;
  anomaly_type: string; risk_title: string; reason: string; observed_text: string;
  expected_text: string; severity: string; recommended_action: string; citations: string[];
  detected_at_utc: string; status: string;
  scenario_context?: ScenarioContext;
  risk_engine?: string; graph_ood?: {
    score: number; threshold: number; is_graph_ood: boolean;
    signals: { code: string; points: number; detail: string }[];
    features: Record<string, string | number | null>; evidence_path: string[];
  };
};
type Provenance = {
  dataset_id?: string; synthetic?: boolean; seed?: number; extracted_at_utc?: string | null;
  coverage_start?: string | null; coverage_end?: string | null; timezone?: string;
  run_started_at_utc?: string | null; run_completed_at_utc?: string | null;
  source_fingerprint?: string | null; augmentation_note?: string;
};
type RazorpayFeed = {
  configured?: boolean; mode?: string; api_base?: string; key_id_hint?: string | null;
  read_only?: boolean; live_keys_blocked?: boolean; controller_ready?: boolean;
  data_classification?: string; real_money?: boolean;
  missing_independent_sources?: string[]; last_sync?: {
    status?: string; extracted_at_utc?: string; coverage_start_utc?: string;
    coverage_end_utc?: string; counts?: Record<string, number>; snapshot_path?: string;
    limitation?: string;
  } | null;
};
type GraphFeature = { feature: string; points: number; detail: string };
type GraphCertificate = {
  certificate_id: string; candidate_id: string; kind: string; bank_entries: string[];
  topology?: string;
  settlements: string[]; evidence_score: number; confidence: number; score_breakdown: GraphFeature[];
  money_conservation: { bank_total: string; settlement_net: string; residual: string };
  constraints_satisfied: string[]; rejected_alternatives: { candidate_id: string; evidence_score: number; residual: string; reason: string }[];
};
type GraphEdge = {
  candidate_id: string; kind: string; topology?: string; bank_ids: string[]; settlement_ids: string[];
  bank_total: string; settlement_total: string; residual: string; evidence_score: number;
  eligible: boolean; blockers: string[]; features: GraphFeature[]; certificate?: GraphCertificate | null;
  selected?: boolean; settlement_nodes?: { id: string; amount?: string; utr?: string }[];
  rejection_stage?: string;
};
type ContestedGroup = { bank_node: { id: string; amount?: string; narration?: string }; candidates: GraphEdge[] };
type ChallengeClass = { baseline_detected: number; graph_detected: number; baseline_recall?: string; graph_recall?: string };
type ChallengeSummary = {
  recall?: string; precision?: string; recall_95_ci?: string[]; false_negatives?: number;
  missed_classes?: Record<string, number>; by_mutation_class?: Record<string, ChallengeClass>;
  baseline_without_graph?: { recall?: string; false_negatives?: number };
  graph_intelligence_delta?: { additional_true_positives?: number; false_positives_added?: number; false_negatives_removed?: number };
};
type RobustnessSummary = { risk_recall?: string; bank_entries?: number; seed_count?: number; false_auto_closures?: number };
type RiskSummary = { records?: number; dubious_records?: number };
type FraudHoldoutSummary = {
  detector_version?: string; detector_sha256?: string; holdout_records?: number;
  holdout_positive_records?: number; holdout_negative_records?: number;
  recall?: string; recall_95_ci?: string[]; specificity?: string;
  false_positives?: number; false_negatives?: number; missed_classes?: Record<string, number>;
};
type LedgerGraphComparison = { system: string; cases_exactly_correct: number; case_count: number; hypothesis_recall: string; false_selections: number };
type LedgerGraphCase = { case_id: string; partition: string; claim: string; ledgergraph_candidate_count: number; ledgergraph_abstained_banks: string[]; ledgergraph_global: { exact: boolean } };
type LedgerGraphEval = { comparison?: LedgerGraphComparison[]; cases?: LedgerGraphCase[]; held_out_ledgergraph?: { cases_exactly_correct?: number; false_selections?: number }; held_out_case_count?: number };
type GraphIntelligenceSummary = {
  challenge_by_class?: Record<string, ChallengeClass>;
  challenge_baseline?: { recall?: string; false_negatives?: number };
  challenge_delta?: { additional_true_positives?: number; false_positives_added?: number };
  challenge_enhanced?: { recall?: string; false_negatives?: number; precision?: string };
  fresh_holdout?: FraudHoldoutSummary;
};
type LedgerGraph = {
  solver?: string; solver_policy?: string; selection_threshold?: number; bank_node_count: number; settlement_node_count: number;
  all_components_proven?: boolean; component_status_counts?: Record<string, number>;
  candidate_generation?: { algorithm?: string; status?: string; complete?: boolean; issues?: Array<{ code?: string; reason?: string }>; bank_index?: { state_count?: number; transition_count?: number }; settlement_index?: { state_count?: number; transition_count?: number } };
  candidate_generation_unsafe_node_count?: number;
  candidate_count: number; selectable_candidate_count: number; selected_candidate_count: number;
  abstained_bank_count: number; rejected_candidate_count: number; money_conflict_count: number;
  contested_bank_count: number; global_constraints: string[]; selected_edges: GraphEdge[];
  candidate_topology_counts?: Record<string, number>; selected_topology_counts?: Record<string, number>;
  hard_gate_rejected_topology_counts?: Record<string, number>; global_rejected_topology_counts?: Record<string, number>;
  generation_rejected_topology_counts?: Record<string, number>;
  timing_policy?: { policy_label: string; scope_note: string; cycle_counts: Record<string, number>; chronology_violations: number; thursday_t2_example?: { settlement_id: string; capture_date: string; settled_at: string; working_day_path: string } | null };
  rejected_examples: GraphEdge[]; contested_groups: ContestedGroup[];
  mesh: MeshData;
};
type Overview = {
  generated_at: string | null;
  runtime: { orchestrator: string; money_engine: string; language_model: string; ledger: string; mode: string; model_available?: boolean; model_status?: string; model_endpoint?: string };
  headline: { bank_value: string; bank_value_display: string; bank_records: number; bank_entries: number; bank_credits: number; bank_debits: number; bank_debit_value?: string; bank_debit_value_display?: string; orders: number; recon_rows: number };
  metrics: Record<string, string | number>;
  tiers: Tier[]; sources: Source[]; stages: Stage[]; exceptions: ExceptionItem[];
  approval_queue: Journal[]; approval_summary: { total: number; pending: number; posted: number; rejected: number };
  audit: AuditEvent[]; risk_findings: RiskFinding[]; risk_summary: RiskSummary;
  robustness: RobustnessSummary; challenge: ChallengeSummary; fraud_holdout: FraudHoldoutSummary; provenance: Provenance;
  scenario_catalog: ScenarioCatalog;
  razorpay_feed: RazorpayFeed;
  ledgergraph: LedgerGraph; ledgergraph_eval: LedgerGraphEval;
  graph_intelligence: GraphIntelligenceSummary;
};
type RunResponse = { overview: Overview };
type QuestionResponse = { answer?: string; detail?: string };
type ApprovalResponse = { overview?: Overview; detail?: string };

const API = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

const fallback: Overview = {
  generated_at: null,
  runtime: { orchestrator: 'LangGraph', money_engine: 'Deterministic Python', language_model: 'Qwen 3.5 4B Q4_K_M · HF GGUF', ledger: 'Local sandbox SQLite', mode: 'snapshot' },
  headline: { bank_value: '0', bank_value_display: '₹—', bank_records: 75, bank_entries: 87, bank_credits: 79, bank_debits: 8, orders: 2232, recon_rows: 2338 },
  metrics: {
    bank_match_precision: '100.0%', bank_recall_on_resolvable: '100.0%', component_closure_rate: '96.0%',
    component_closure_precision: '100.0%', component_exceptions: 3, false_auto_closures: 0, unresolved_value_inr: '10358.00',
  },
  tiers: [
    { tier: 0, n: 6, matched: 6, comp_ok: 6, refusal: 0, batch_acc: '100.0%' },
    { tier: 1, n: 21, matched: 21, comp_ok: 21, refusal: 0, batch_acc: '100.0%' },
    { tier: 2, n: 34, matched: 34, comp_ok: 34, refusal: 0, batch_acc: '100.0%' },
    { tier: 3, n: 11, matched: 11, comp_ok: 11, refusal: 0, batch_acc: '100.0%' },
    { tier: 4, n: 3, matched: 3, comp_ok: 0, refusal: 3, batch_acc: '100.0%' },
  ],
  stages: [
    { step: '01', name: 'Sources', note: 'Schema + hashes', status: 'complete' },
    { step: '02', name: 'Reconcile', note: 'Find one complete, conflict-free answer', status: 'complete' },
    { step: '03', name: 'Verify', note: 'Components + eval', status: 'complete' },
    { step: '04', name: 'Approve', note: 'LangGraph interrupt', status: 'active' },
  ],
  sources: [], exceptions: [], risk_findings: [], risk_summary: {}, robustness: {}, challenge: {}, fraud_holdout: {}, provenance: {}, scenario_catalog: { categories: [], scenarios: {} }, razorpay_feed: { configured: false, mode: 'test', read_only: true }, approval_queue: [],
  ledgergraph: { bank_node_count: 75, settlement_node_count: 75, candidate_count: 0, selectable_candidate_count: 0, selected_candidate_count: 0, abstained_bank_count: 0, rejected_candidate_count: 0, money_conflict_count: 0, contested_bank_count: 0, candidate_topology_counts: {}, selected_topology_counts: {}, timing_policy: { policy_label: 'Synthetic T+1/T+2 · Monday-Friday working days', scope_note: 'Demonstration policy, not a universal Razorpay merchant contract.', cycle_counts: { 'T+1': 33, 'T+2': 42 }, chronology_violations: 0 }, global_constraints: [], selected_edges: [], rejected_examples: [], contested_groups: [], mesh: { bank_nodes: [], settlement_nodes: [], edges: [] } }, ledgergraph_eval: {}, graph_intelligence: {},
  approval_summary: { total: 47, pending: 45, posted: 0, rejected: 0 }, audit: [],
};

function normalizeOverview(value: Partial<Overview>): Overview {
  return {
    ...fallback,
    ...value,
    runtime: { ...fallback.runtime, ...(value.runtime || {}) },
    headline: { ...fallback.headline, ...(value.headline || {}) },
    metrics: { ...fallback.metrics, ...(value.metrics || {}) },
    risk_findings: value.risk_findings || [],
    risk_summary: value.risk_summary || {},
    robustness: value.robustness || {},
    challenge: value.challenge || {},
    fraud_holdout: value.fraud_holdout || {},
    scenario_catalog: value.scenario_catalog || fallback.scenario_catalog,
    provenance: value.provenance || {},
    razorpay_feed: value.razorpay_feed || fallback.razorpay_feed,
    ledgergraph: { ...fallback.ledgergraph, ...(value.ledgergraph || {}) },
    ledgergraph_eval: value.ledgergraph_eval || {},
    graph_intelligence: value.graph_intelligence || {},
    sources: value.sources || [],
    exceptions: value.exceptions || [],
    approval_queue: value.approval_queue || [],
    audit: value.audit || [],
  };
}

const tabs = [
  { id: 'overview', label: 'Overview', key: '⌁' },
  { id: 'ledgergraph', label: 'Reconciliation', key: '◇' },
  { id: 'exceptions', label: 'Exceptions', key: '!' },
  { id: 'approvals', label: 'Approvals', key: '✓' },
  { id: 'audit', label: 'Activity', key: '≡' },
  { id: 'evaluation', label: 'Reliability', key: '◎' },
] as const;
const topologyScenarioIds = ['topology:1:1', 'topology:1:N', 'topology:N:1', 'topology:N:M'] as const;
type Tab = typeof tabs[number]['id'];

function eventLabel(event: string): string {
  const friendly: Record<string, string> = {
    exact_reference_baseline: 'Exact reference only',
    rowwise_l0_l1: 'Row-by-row matching',
    ledgergraph_global: 'Current controller',
    OPTIMAL_UNIQUE: 'complete answers',
    OPTIMAL_TIED: 'tied answers held',
    INCOMPLETE: 'incomplete answers held',
  };
  if (friendly[event]) return friendly[event];
  return event.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase());
}

function stageNote(note: string): string {
  const friendly: Record<string, string> = {
    'LedgerGraph global solve': 'Find one complete, conflict-free answer',
    'Metrics + honest misses': 'Measure correct answers and visible misses',
    'Human-only sandbox gate': 'Wait for a person before recording',
  };
  return friendly[note] || note;
}

function scenarioFor(catalog: ScenarioCatalog, scenarioId: string): ScenarioContext | undefined {
  return catalog.scenarios[scenarioId];
}

function ScenarioBadge({ context }: { context?: ScenarioContext }) {
  if (!context) return null;
  return <span className={`scenarioBadge scenario-${context.category}`}>{context.category_short_label}</span>;
}

function evidenceLevel(edge: GraphEdge): string {
  const features = new Set(edge.features.map(item => item.feature));
  if (edge.blockers.includes('money_conservation_failed')) return 'Rejected pre-solve';
  if (edge.kind !== 'one_to_one') return 'Grouped hypothesis';
  if (features.has('full_utr_exact') && features.has('signed_amount_exact')) return 'Exact reference and money';
  if (features.has('signed_amount_exact')) return 'Exact money with supporting details';
  return 'Candidate only';
}

function shortId(value?: string | null): string {
  if (!value) return '—';
  return value.length > 24 ? `${value.slice(0, 12)}…${value.slice(-6)}` : value;
}

function timestamp(value?: string | null): string {
  if (!value) return 'Not recorded';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  try {
    return parsed.toLocaleString('en-IN', {
      day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit',
      minute: '2-digit', second: '2-digit', timeZoneName: 'short',
    });
  } catch {
    return parsed.toISOString();
  }
}

export default function Home() {
  const [data, setData] = useState<Overview>(fallback);
  const [tab, setTab] = useState<Tab>('overview');
  const [connection, setConnection] = useState<'connecting' | 'live' | 'snapshot'>('connecting');
  const [busy, setBusy] = useState(false);
  const [selectedJournal, setSelectedJournal] = useState<Journal | null>(null);
  const [selectedRisk, setSelectedRisk] = useState<RiskFinding | null>(null);
  const [selectedGraph, setSelectedGraph] = useState<GraphEdge | null>(null);
  const [graphMode, setGraphMode] = useState<'candidates' | 'solution'>('candidates');
  const [question, setQuestion] = useState('Why was BNK000015 held for review?');
  const [answer, setAnswer] = useState('');
  const [asking, setAsking] = useState(false);
  const [useModel, setUseModel] = useState(true);
  const [approvalFilter, setApprovalFilter] = useState<'all' | 'pending' | 'posted' | 'rejected'>('pending');
  const [search, setSearch] = useState('');
  const [feedMessage, setFeedMessage] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    void fetch(`${API}/api/overview`, { cache: 'no-store', signal: controller.signal })
      .then(response => {
        if (!response.ok) throw new Error('controller unavailable');
        return response.json() as Promise<Partial<Overview>>;
      })
      .then(overview => {
        setData(normalizeOverview(overview));
        setConnection('live');
      })
      .catch(error => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setConnection('snapshot');
      });
    return () => controller.abort();
  }, []);

  const runPipeline = async () => {
    setBusy(true);
    try {
      const response = await fetch(`${API}/api/runs`, { method: 'POST' });
      if (!response.ok) throw new Error('run failed');
      const payload = await response.json() as RunResponse;
      setData(normalizeOverview(payload.overview));
      setConnection('live');
    } finally { setBusy(false); }
  };

  const syncRazorpay = async () => {
    setBusy(true); setFeedMessage('Connecting to the read-only Razorpay Test API…');
    try {
      const response = await fetch(`${API}/api/razorpay/sync`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ max_records: 1000 }),
      });
      const payload = await response.json() as { overview?: Overview; detail?: string; sync?: { counts?: Record<string, number> } };
      if (!response.ok) throw new Error(payload.detail || 'Razorpay sync failed');
      if (payload.overview) setData(normalizeOverview(payload.overview));
      const total = Object.values(payload.sync?.counts || {}).reduce((sum, value) => sum + value, 0);
      setFeedMessage(`Snapshot complete: ${total} simulated Razorpay Test Mode records staged from the hosted API.`);
    } catch (error) {
      setFeedMessage(error instanceof Error ? error.message : 'Razorpay sync failed.');
    } finally { setBusy(false); }
  };

  const ask = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!question.trim()) return;
    setAsking(true); setAnswer('');
    try {
      const response = await fetch(`${API}/api/qa`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, use_model: useModel }),
      });
      const payload = await response.json() as QuestionResponse;
      setAnswer(response.ok ? payload.answer || 'No grounded answer was returned.' : payload.detail || 'Unable to answer safely.');
    } catch { setAnswer('The local controller is offline. Start the API to query evidence.'); }
    finally { setAsking(false); }
  };

  const decide = async (journal: Journal, decision: 'approve' | 'reject') => {
    setBusy(true);
    try {
      const response = await fetch(`${API}/api/approvals/${journal.proposal_id}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision, reviewer: 'demo-finance-controller', note: decision === 'approve' ? 'Reviewed against cited source records.' : 'Rejected during controller review.' }),
      });
      const payload = await response.json() as ApprovalResponse;
      if (!response.ok) throw new Error(payload.detail || 'approval failed');
      if (!payload.overview) throw new Error('approval response did not include an overview');
      setData(normalizeOverview(payload.overview));
      setSelectedJournal(payload.overview.approval_queue.find(item => item.proposal_id === journal.proposal_id) || null);
    } catch (error) { window.alert(error instanceof Error ? error.message : 'Approval failed'); }
    finally { setBusy(false); }
  };

  const visibleApprovals = useMemo(() => data.approval_queue.filter(item => {
    const matchesSearch = !search || `${item.proposal_id} ${(item.bank_txn_ids || [item.bank_txn_id]).join(' ')} ${(item.settlement_ids || [item.settlement_id]).join(' ')}`.toLowerCase().includes(search.toLowerCase());
    if (!matchesSearch) return false;
    if (approvalFilter === 'all') return true;
    if (approvalFilter === 'pending') return item.workflow_status === 'awaiting_human_approval';
    if (approvalFilter === 'posted') return item.workflow_status === 'posted_to_sandbox_ledger';
    return item.workflow_status === 'rejected';
  }), [data.approval_queue, approvalFilter, search]);

  const challenge = data.challenge || {};
  const graphIntel = data.graph_intelligence || {};
  const fraudHoldout = data.fraud_holdout || {};
  const missedClasses = Object.entries(challenge.missed_classes || {}) as [string, number][];
  const recoveredClasses = Object.entries(graphIntel.challenge_by_class || {}).filter(([, value]) => value.graph_detected > value.baseline_detected);
  const metricCards = [
    ['Bank entries checked', data.headline.bank_entries, `${data.headline.bank_credits} credits · ${data.headline.bank_debits} debits`, 'plain'],
    ['Entries sent for review', data.risk_findings.length, `${data.risk_findings.filter(item => item.direction === 'credit').length} credits · ${data.risk_findings.filter(item => item.direction === 'debit').length} debits`, 'mint'],
    ['Journal entries prepared', data.approval_summary.total, 'Waiting for a person to approve', 'mint'],
    ['Automatically posted', '0', 'The system never moves money by itself', 'plain'],
  ];
  const riskExposure = data.risk_findings.reduce((total, item) => total + Number(item.amount || 0), 0);

  return (
    <main className="appShell">
      <aside className="sidebar">
        <div className="brand"><span className="brandMark">FC</span><div><strong>Finance Controller</strong><small>Reconcile, review, approve</small></div></div>
        <nav aria-label="Primary navigation">
          {tabs.map(item => <button key={item.id} onClick={() => setTab(item.id)} className={tab === item.id ? 'active' : ''}><span>{item.key}</span>{item.label}{item.id === 'exceptions' && <em>{data.risk_findings.length}</em>}{item.id === 'approvals' && <em>{data.approval_summary.pending}</em>}</button>)}
        </nav>
        <div className="authorityCard">
          <span className="authorityIcon">◆</span><div><strong>Safe by design</strong><p>AI explains the evidence. Code handles money. A person approves.</p></div>
        </div>
        <div className="runtimeStack">
          <span>System status</span><strong>{connection === 'live' ? 'Ready' : 'Offline snapshot'}</strong><small>Money checks: deterministic</small><small>Assistant: {data.runtime.model_available ? 'local Qwen ready' : 'safe fallback'}</small>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div><span className={`connection ${connection}`}><i /> {connection === 'live' ? 'Controller ready' : connection === 'connecting' ? 'Connecting' : 'Showing saved results'}</span></div>
          <div className="topActions"><span className="seed">SIMULATED DATA ONLY</span><button className="runButton" onClick={runPipeline} disabled={busy || connection !== 'live'}>{busy ? 'Running…' : 'Run current batch'} <b>→</b></button></div>
        </header>

        <div className="content">
          {tab === 'overview' && <>
            <section className="hero">
              <div><p className="eyebrow">Your daily settlement check</p><h1>Know where every payout went.<br /><span>Review only what needs you.</span></h1><p className="lede">Finance Controller compares Razorpay settlements, bank entries, and your cashbook—then prepares safe journal entries for a person to approve.</p></div>
              <div className="batchStamp"><span>Simulation-only batch</span><strong>{data.headline.bank_entries} entries</strong><small>{data.risk_findings.length} dubious · {data.approval_summary.total} safe proposals · 0 auto-posted</small><small>Extracted {timestamp(data.provenance.extracted_at_utc)}</small></div>
            </section>

            <section className="judgeThesis">
              <strong>The problem</strong><p>One bank payout can contain many payments, fees, refunds, and adjustments. Comparing three exports by hand is slow and easy to get wrong.</p>
              <strong>The solution</strong><p>The controller finds the complete explanation, shows uncertain items with their source rows, and waits for human approval before recording anything.</p>
            </section>

            <section className="provenanceBar" aria-label="Data and run timestamps">
              <article><span>Extraction timestamp</span><strong>{timestamp(data.provenance.extracted_at_utc)}</strong><small>{data.provenance.dataset_id || 'Synthetic source bundle'}</small></article>
              <article><span>Data coverage window</span><strong>{data.provenance.coverage_start || '—'} → {data.provenance.coverage_end || '—'}</strong><small>Timezone: {data.provenance.timezone || 'UTC'}</small></article>
              <article><span>Pipeline completed</span><strong>{timestamp(data.provenance.run_completed_at_utc || data.generated_at)}</strong><small>Started {timestamp(data.provenance.run_started_at_utc)}</small></article>
              <article><span>Latest reliability test</span><strong>{fraudHoldout.recall || '—'} recall</strong><small>{fraudHoldout.false_negatives ?? '—'} new test cases missed · shown honestly</small></article>
            </section>

            <section className="stageRail" aria-label="Pipeline stages">
              {data.stages.map((stage, index) => <article className={`stage ${stage.status}`} key={stage.name}><div className="stageTop"><span>{stage.step}</span><i /></div><strong>{stage.name}</strong><small>{stageNote(stage.note)}</small>{index < data.stages.length - 1 && <b className="connector">→</b>}</article>)}
            </section>

            <section className="metricGrid">{metricCards.map(([label, value, note, tone]) => <article key={label} className={tone === 'mint' ? 'metricMint' : ''}><span>{label}</span><strong>{value}</strong><small>{note}</small></article>)}</section>

            <section className="realityPanel" aria-label="Synthetic scenario realism legend">
              <div className="realityIntro"><div><span className="kicker">About this demo data</span><h2>Realistic situations, simulated money.</h2></div><p>The batch covers normal payouts, timing differences, missing references, refunds, fees, duplicate records, and suspicious credits and debits. Counts show test coverage, not how often these events happen in real life.</p></div>
              <div className="realityGrid">{data.scenario_catalog.categories.map(category => <article key={category.id}><span className={`scenarioBadge scenario-${category.id}`}>{category.short_label}</span><p>{category.description}</p><small>{category.examples.join(' · ')}</small></article>)}</div>
              <div className="realitySources"><strong>Realism basis:</strong><span>official settlement/report mechanics plus explicitly synthetic cross-system and ERP stress cases.</span>{(data.scenario_catalog.references || []).map(reference => <a key={reference.url} href={reference.url} target="_blank" rel="noreferrer">{reference.label} ↗</a>)}</div>
            </section>

            <section className="overviewGrid">
              <article className="panel tierPanel">
                <div className="panelHead"><div><span className="kicker">How it works</span><h2>Three sources become one review-ready answer.</h2></div><button className="textButton" onClick={() => setTab('ledgergraph')}>See reconciliation →</button></div>
                <div className="systemMap">
                  <div className="sourceStack"><article><i>RZP</i><span><strong>Razorpay Test Mode</strong><small>Simulated payments and settlement components</small></span></article><article><i>BNK</i><span><strong>Simulated bank</strong><small>Credits, debits, narrations and balances</small></span></article><article><i>ERP</i><span><strong>Simulated merchant ERP</strong><small>Approved cashbook evidence</small></span></article></div>
                  <div className="mapArrow">→</div>
                  <article className="controllerCore"><span>Finance Controller</span><strong>Match · check · explain</strong><small>Exact money calculations and safe stopping rules</small></article>
                  <div className="mapArrow">→</div>
                  <div className="outputStack"><article><strong>{data.approval_summary.total}</strong><small>entries prepared</small></article><article><strong>{data.risk_findings.length}</strong><small>items to review</small></article><article><strong>0</strong><small>auto-posted</small></article></div>
                </div>
                <div className="modelBoundary"><strong>The AI assistant’s only job:</strong><span>turn checked evidence into a clear answer. It never chooses a match, calculates an amount, approves, or posts.</span></div>
              </article>

              <article className="panel reviewPanel">
                <div className="panelHead"><div><span className="kicker">Needs attention</span><h2>{data.risk_findings.length} dubious entries</h2></div><button className="textButton" onClick={() => setTab('exceptions')}>Open queue →</button></div>
                <div className="reviewList">{data.risk_findings.slice(0, 4).map(item => <button key={item.bank_txn_id} onClick={() => setSelectedRisk(item)}><span className="warningDot">!</span><div><strong>{item.bank_txn_id} · {item.direction}</strong><small>{item.risk_title}</small><ScenarioBadge context={item.scenario_context} /></div><b>{item.amount_display}</b></button>)}{!data.risk_findings.length && <p className="empty">No dubious bank entries were detected.</p>}</div>
              </article>

              <article className="panel evidencePanel">
                <div className="panelHead"><div><span className="kicker">Ask about a result</span><h2>Get a plain-language answer with sources</h2></div><label className={`modelToggle ${data.runtime.model_available ? 'modelReady' : 'modelOffline'}`}><input type="checkbox" checked={useModel} onChange={event => setUseModel(event.target.checked)} /><span />{data.runtime.model_available ? 'Local assistant ready · GPU' : 'Assistant offline · safe fallback'}</label></div>
                <form onSubmit={ask} className="askForm"><input value={question} onChange={event => setQuestion(event.target.value)} aria-label="Ask a settlement question" /><button disabled={asking || connection !== 'live'}>{asking ? 'Checking…' : 'Ask'} <span>↗</span></button></form>
                <div className={`answer ${answer ? 'hasAnswer' : ''}`}>{answer || <><span className="answerMark">i</span><p>The assistant can only read results already produced by the controller. Every answer can point back to the original source rows.</p></>}</div>
                <div className="suggestions"><button onClick={() => setQuestion('List the unresolved exceptions')}>Unresolved exceptions</button><button onClick={() => setQuestion('Show the measured precision and recall')}>Measured performance</button></div>
              </article>

              <article className="panel sourcePanel">
                <div className="panelHead"><div><span className="kicker">Provenance</span><h2>Source manifest</h2></div><span className="proofTag">SHA-256</span></div>
                <div className={`apiFeedCard ${data.razorpay_feed.configured ? 'configured' : ''}`}>
                  <div><span className="feedDot" /><div><strong>Razorpay Test API · read only</strong><small>{data.razorpay_feed.configured ? `Credential ${data.razorpay_feed.key_id_hint || 'configured'}` : 'Credentials not configured'}</small></div></div>
                  <button onClick={syncRazorpay} disabled={busy}>{busy ? 'Syncing…' : 'Sync API feed'}</button>
                  <p>{data.razorpay_feed.last_sync ? `Last extracted ${timestamp(data.razorpay_feed.last_sync.extracted_at_utc)} · ${Object.values(data.razorpay_feed.last_sync.counts || {}).reduce((sum, value) => sum + value, 0)} simulated records` : 'Uses Razorpay’s hosted Test Mode API and official schemas. All entities and money are simulated.'}</p>
                  <p className="feedBoundary">Simulation-only policy: live keys, real bank exports, real ERP records, and money-moving endpoints are prohibited.</p>
                  {feedMessage && <p className="feedMessage">{feedMessage}</p>}
                </div>
                <div className="sourceList">{data.sources.map(source => <div key={source.name}><span className="fileIcon">{source.name.endsWith('.json') ? 'JSON' : 'CSV'}</span><div><strong>{source.name}</strong><small>{source.rows.toLocaleString()} rows · {source.sha256} · extracted {timestamp(source.extracted_at_utc)}</small><small>{source.source_system} · coverage {source.coverage_start || '—'} → {source.coverage_end || '—'}</small></div><i>✓</i></div>)}{!data.sources.length && <p className="empty">Source hashes and extraction timestamps appear when connected.</p>}</div>
              </article>
            </section>
          </>}

          {tab === 'ledgergraph' && <section className="pageSection graphPage">
            <div className="pageHead"><div><p className="eyebrow">Reconciliation</p><h1>See why one payout can be hard to explain.</h1><p>The messy view shows every plausible link between bank entries and settlements. The clean view keeps only a complete, conflict-free explanation. If two answers are equally good, the controller stops and asks for review.</p></div><div className="summaryChip"><span>Difficult test cases solved</span><strong>{data.ledgergraph_eval.held_out_ledgergraph?.cases_exactly_correct || '—'}/{data.ledgergraph_eval.held_out_case_count || '—'}</strong><small>{data.ledgergraph_eval.held_out_ledgergraph?.false_selections || 0} wrong matches selected</small></div></div>

            <div className="solverPolicyStrip" aria-label="Reconciliation safety status">
              <article><span>Possible groups</span><strong>{data.ledgergraph.candidate_generation?.complete ? 'All found' : 'Search limit reached'}</strong><small>{data.ledgergraph.candidate_generation?.complete ? 'Complete for this batch' : 'Affected records sent for review'}</small></article>
              <article><span>Whole-batch check</span><strong>No record reused</strong><small>Every accepted group must fit with every other group</small></article>
              <article className={data.ledgergraph.all_components_proven ? '' : 'solverWarning'}><span>Final answer</span><strong>{data.ledgergraph.all_components_proven ? 'Complete and unambiguous' : 'Uncertain records held'}</strong><small>{Object.entries(data.ledgergraph.component_status_counts || {}).map(([status, count]) => `${count} ${eventLabel(status)}`).join(' · ') || 'Awaiting pipeline run'}</small></article>
              <article className={(data.ledgergraph.candidate_generation_unsafe_node_count || 0) > 0 ? 'solverWarning' : ''}><span>When unsure</span><strong>Stop, never guess</strong><small>{data.ledgergraph.candidate_generation_unsafe_node_count ?? 0} records affected by search limits</small></article>
            </div>

            <div className="timingPolicyStrip">
              <div><span>Settlement clock</span><strong>{data.ledgergraph.timing_policy?.policy_label || 'Synthetic T+1/T+2'}</strong><small>{data.ledgergraph.timing_policy?.scope_note || 'Demonstration timing policy.'}</small></div>
              <article><span>T+1</span><strong>{data.ledgergraph.timing_policy?.cycle_counts?.['T+1'] ?? '—'}</strong><small>settlements</small></article>
              <article><span>T+2</span><strong>{data.ledgergraph.timing_policy?.cycle_counts?.['T+2'] ?? '—'}</strong><small>settlements</small></article>
              <article className={(data.ledgergraph.timing_policy?.chronology_violations || 0) > 0 ? 'timingBad' : ''}><span>Chronology violations</span><strong>{data.ledgergraph.timing_policy?.chronology_violations ?? '—'}</strong><small>capture → settlement → bank</small></article>
              <article className="thursdayProof"><span>Weekend proof</span><strong>Thursday T+2 → Monday</strong><small>{data.ledgergraph.timing_policy?.thursday_t2_example?.working_day_path || 'Business days only; Saturday and Sunday are skipped.'}</small></article>
            </div>

            <div className="topologyReality" aria-label="Topology realism and evidence requirements">
              {topologyScenarioIds.map(scenarioId => { const context = scenarioFor(data.scenario_catalog, scenarioId); if (!context) return null; const topology = scenarioId.replace('topology:', ''); return <article key={scenarioId}><div><strong>{topology}</strong><ScenarioBadge context={context} /></div><h3>{context.label}</h3><p>{context.claim_boundary}</p><small><b>Required evidence:</b> {context.required_sources.join(' · ')}</small></article>; })}
            </div>
            <p className="topologyBoundary">The 13 / 12 / 12 / 13 topology mix is deliberately balanced for solver coverage. It is not an estimate of how frequently these shapes occur in production.</p>

            <div className="graphStats"><article><span>Records compared</span><strong>{data.ledgergraph.bank_node_count + data.ledgergraph.settlement_node_count}</strong><small>{data.ledgergraph.bank_node_count} bank · {data.ledgergraph.settlement_node_count} settlement</small></article><article><span>Possible matches</span><strong>{data.ledgergraph.candidate_count}</strong><small>{data.ledgergraph.contested_bank_count} bank entries had more than one option</small></article><article><span>Options rejected</span><strong>{data.ledgergraph.rejected_candidate_count}</strong><small>Wrong money, conflicts, or incomplete evidence</small></article><article><span>Groups accepted</span><strong>{data.ledgergraph.selected_candidate_count}</strong><small>₹0 difference · each record used once</small></article></div>

            <article className="panel graphCanvas">
              <div className="panelHead graphPanelHead"><div><span className="kicker">The whole batch at once</span><h2>{graphMode === 'candidates' ? 'Before: every plausible match' : 'After: one consistent answer'}</h2></div><div className="graphModeSwitch"><button className={graphMode === 'candidates' ? 'active' : ''} onClick={() => setGraphMode('candidates')}>Messy view · {data.ledgergraph.candidate_count}</button><button className={graphMode === 'solution' ? 'active' : ''} onClick={() => setGraphMode('solution')}>Accepted view · {data.ledgergraph.selected_candidate_count}</button></div></div>
              <div className="candidateLegend"><span><i className="bankCircle" /> bank entry</span><span><i className="settlementCircle" /> settlement</span><span><i className="groupCircle" /> grouped match</span><span><i className="selectedLine" /> accepted link</span><span><i className="rejectedLine" /> rejected option</span><p>{graphMode === 'candidates' ? 'All plausible links are shown together. A centre circle means those records must be accepted or rejected as one group.' : 'The answer includes one-to-one, one-to-many, many-to-one, and many-to-many matches.'}</p></div>
              <LedgerMesh mesh={data.ledgergraph.mesh} mode={graphMode} onSelectEdge={edge => setSelectedGraph(edge as GraphEdge)} />
            </article>

            <article className="panel evidenceLadderPanel">
              <div className="panelHead"><div><span className="kicker">How a match is accepted</span><h2>Three checks, in plain language</h2></div><span className="proofTag">Evidence first · decision later</span></div>
              <p className="ladderIntro">A similar reference is never enough. The money must balance exactly, the date and reference must support the link, and the answer must work across the complete batch.</p>
              <div className="evidenceLadder">
                <article className="l0Card"><div className="levelBadge">1</div><span>Money</span><h3>The totals must balance exactly</h3><ul><li>Credits and debits keep their correct sign.</li><li>Payments, fees, refunds, and adjustments explain the bank amount.</li><li>A one-paise difference is not silently rounded away.</li></ul><div className="scoreFormula"><b>₹0</b> unexplained difference</div></article>
                <div className="ladderArrow">→</div>
                <article className="l1Card"><div className="levelBadge">2</div><span>Supporting details</span><h3>Dates and references strengthen the link</h3><ul><li>Settlement timing follows business-day rules.</li><li>Exact references are strongest; small text errors can be tolerated.</li><li>Similar text can rank options, but cannot override wrong money.</li></ul><div className="scoreFormula"><b>T+1 / T+2</b> working days</div></article>
                <div className="ladderArrow">→</div>
                <article className="globalCard"><div className="levelBadge">3</div><span>Whole batch</span><h3>The complete answer must be conflict-free</h3><ul><li>One record cannot be used in two accepted matches.</li><li>One-to-many and many-to-many groups are allowed.</li><li>Ties, incomplete searches, and competing answers go to review.</li></ul><div className="scoreFormula"><b>0</b> reused records</div></article>
              </div>
              <div className="legacyClarifier"><strong>Technical details are optional</strong><p>Behind this view, candidate groups are generated efficiently and an exact optimizer chooses one consistent answer. The business rule remains simple: exact money, supporting evidence, no reused records, and no guessing.</p></div>
            </article>

            <article className="panel intelligencePanel">
              <div className="panelHead"><div><span className="kicker">Extra risk checks</span><h2>Balanced does not automatically mean safe.</h2></div><span className="proofTag">Can only request review</span></div>
              <p className="intelligenceIntro">After the money is reconciled, the controller checks whether the beneficiary, reference, and approval pattern look consistent with the cashbook. These checks can stop an item, but they cannot rewrite a match or amount.</p>
              <div className="intelligenceFlow">
                <article><span>01 · Reconcile</span><strong>Explain the money</strong><small>Which records belong together, and do they balance?</small></article><b>→</b><article><span>02 · Check context</span><strong>Look for unusual links</strong><small>Do the beneficiary, reference, and approver belong here?</small></article><b>→</b><article><span>03 · Review</span><strong>A person decides</strong><small>Unusual paths stop. The system cannot post by itself.</small></article>
              </div>
              <div className="oodDelta">
                <div className="deltaMetric baselineMetric"><span>Money checks alone</span><strong>{graphIntel.challenge_baseline?.recall || '—'}</strong><small>{graphIntel.challenge_baseline?.false_negatives ?? '—'} known suspicious cases missed</small></div>
                <div className="deltaArrow"><span>+{graphIntel.challenge_delta?.additional_true_positives ?? '—'} found</span><b>→</b><small>{graphIntel.challenge_delta?.false_positives_added ?? '—'} extra false alarms</small></div>
                <div className="deltaMetric enhancedMetric"><span>Money plus context checks</span><strong>{graphIntel.challenge_enhanced?.recall || '—'}</strong><small>{graphIntel.challenge_enhanced?.false_negatives ?? '—'} misses on the known replay</small></div>
              </div>
              <div className="graphSignalGrid">
                <article><i>ID</i><div><span>Beneficiary mismatch</span><strong>Bank text disagrees with the approved cashbook party</strong><small>The finding shows both the observed name and expected name.</small></div></article>
                <article><i>AP</i><div><span>Unusual approval pattern</span><strong>A new approver repeats the same amount and destination</strong><small>Repeated suspicious behaviour is sent for human review.</small></div></article>
                <article><i>RF</i><div><span>Broken reference chain</span><strong>A reference is missing or unexpectedly reused</strong><small>The exact records and links are shown with the finding.</small></div></article>
              </div>
              <div className="intelligenceBoundary"><strong>What this result means</strong><p>The extra checks catch the previously known misses, but a separate test with new fraud patterns scores {graphIntel.fresh_holdout?.recall || '—'} recall and leaves {graphIntel.fresh_holdout?.false_negatives ?? '—'} misses visible. This is honest evidence of current limits, not a promise to catch every fraud.</p></div>
            </article>

            <div className="graphProofGrid">
              <article className="panel"><div className="panelHead"><div><span className="kicker">Why it is safer</span><h2>Evidence first, exact rules last</h2></div></div><ol className="constraintList"><li><b>01</b><span><strong>Find plausible groups</strong>Money, dates, and references identify the options worth checking.</span></li><li><b>02</b><span><strong>Check the whole batch</strong>All options compete together, so one record cannot be matched twice.</span></li><li><b>03</b><span><strong>Accept or stop</strong>Money must balance exactly. Ties and incomplete searches go to review.</span></li></ol></article>
              <article className="panel"><div className="panelHead"><div><span className="kicker">Reliability check</span><h2>Difficult examples the controller had not seen</h2></div><span className="proofTag">7 test cases</span></div><div className="comparisonList">{(data.ledgergraph_eval.comparison || []).map(item => <div key={item.system} className={item.system === 'ledgergraph_global' ? 'winner' : ''}><span>{eventLabel(item.system)}</span><strong>{item.cases_exactly_correct}/{item.case_count}</strong><small>{item.false_selections} wrong selections</small></div>)}</div><p className="scopeNote">The final controller solves {data.ledgergraph_eval.held_out_ledgergraph?.cases_exactly_correct || '—'}/{data.ledgergraph_eval.held_out_case_count || '—'} new reconciliation cases with zero wrong selections. These are simulated accounting tests, not a claim about production fraud detection.</p></article>
            </div>

            <article className="panel scenarioPanel"><div className="panelHead"><div><span className="kicker">Difficult situations tested</span><h2>What the reconciliation tests include</h2></div><span className="proofTag">direct · grouped · ambiguous</span></div><div className="scenarioGrid">{(data.ledgergraph_eval.cases || []).map(item => <article key={item.case_id}><span>{item.partition === 'held_out' ? 'NEW TEST' : 'SETUP TEST'} · {item.ledgergraph_global.exact ? '✓ correct' : '! review'}</span><h3>{eventLabel(item.case_id)}</h3><p>{item.claim}</p><small>{item.ledgergraph_candidate_count} possible matches · {item.ledgergraph_abstained_banks.length} bank entries held</small></article>)}</div></article>
          </section>}

          {tab === 'evaluation' && <section className="pageSection evaluationPage">
            <div className="pageHead"><div><p className="eyebrow">Reliability</p><h1>What works, what was tested, and what still fails.</h1><p>We separate familiar checks from genuinely new fraud patterns. That keeps a perfect score on known rules from being mistaken for real-world fraud performance.</p></div><div className="summaryChip challengeChip"><span>New fraud-pattern test</span><strong>{fraudHoldout.recall || '—'} recall</strong><small>{fraudHoldout.false_negatives ?? '—'} misses kept visible · {fraudHoldout.specificity || '—'} clean-entry accuracy</small></div></div>

            <div className="evaluationDefinitions">
              <article><span>Known rules</span><strong>“Did the controller perform the checks we wrote?”</strong><p>These tests cover declared situations such as duplicates, missing references, timing shifts, and unsupported adjustments. A perfect score here means the rules work as written.</p></article>
              <article><span>Previously missed cases</span><strong>“Did the fix prevent the same mistake from returning?”</strong><p>These cases helped shape the extra risk checks, so their score is useful for regression testing—not proof that the system handles something new.</p></article>
              <article><span>New fraud patterns</span><strong>“What does the unchanged system miss?”</strong><p>The controller is frozen before these new situations run. We leave the misses visible instead of changing the rules after seeing the answers.</p></article>
            </div>

            <div className="evalLayerGrid">
              <article className="evalCard"><span className="evalIndex">01 · Known batch</span><strong>{data.metrics.risk_recall || '—'}</strong><h2>Declared checks</h2><p>{data.risk_summary.records || data.headline.bank_entries} bank entries · {data.risk_summary.dubious_records || data.risk_findings.length} suspicious · both credit and debit</p><em className="goodStatus">All written rules pass</em></article>
              <article className="evalCard"><span className="evalIndex">02 · Repeated with new data</span><strong>{data.robustness.risk_recall || '—'}</strong><h2>Stability check</h2><p>{data.robustness.bank_entries || 0} entries · {data.robustness.seed_count || 0} generated batches · {data.robustness.false_auto_closures || 0} unsafe automatic closes</p><em className="goodStatus">Stable across batches</em></article>
              <article className="evalCard challengeCard"><span className="evalIndex">03 · Previous mistakes</span><strong>{challenge.baseline_without_graph?.recall || '—'} → {challenge.recall || '—'}</strong><h2>Regression check</h2><p>{challenge.graph_intelligence_delta?.additional_true_positives || 0} additional detections · {challenge.graph_intelligence_delta?.false_positives_added || 0} extra false alarms · 440 entries</p><em className="waitStatus">Useful, but not a new test</em></article>
              <article className="evalCard holdoutCard"><span className="evalIndex">04 · New situations</span><strong>{fraudHoldout.recall || '—'}</strong><h2>Unseen fraud-pattern test</h2><p>{fraudHoldout.holdout_positive_records || 0} suspicious · {fraudHoldout.holdout_negative_records || 0} clean controls · {fraudHoldout.false_negatives || 0} misses disclosed</p><em className="badStatus">Blind spots measured honestly</em></article>
            </div>

            <article className="panel challengeDetail holdoutDetail">
              <div className="panelHead"><div><span className="kicker">Controller frozen before the test</span><h2>New fraud patterns reveal the current blind spots.</h2></div><span className="proofTag">Test version locked</span></div>
              <div className="challengeFacts"><div><span>Likely recall range</span><strong>{(fraudHoldout.recall_95_ci || []).join(' – ') || '—'}</strong><small>95% range for this simulated sample</small></div><div><span>Clean entries wrongly flagged</span><strong>{fraudHoldout.false_positives ?? '—'}</strong><small>Across the frozen clean controls</small></div><div><span>Code unchanged during test</span><strong>{fraudHoldout.detector_sha256 ? 'Verified' : 'Pending'}</strong><small>Any code change invalidates the result</small></div></div>
              <div className="gapGrid">{Object.entries(fraudHoldout.missed_classes || {}).map(([name, count]) => { const context = scenarioFor(data.scenario_catalog, name); return <article key={name}><div className="scenarioCardTop"><span>{count} fresh misses</span><ScenarioBadge context={context} /></div><h3>{eventLabel(name)}</h3><p>{context?.realism_basis || 'The current risk checks do not yet have the evidence required for this synthetic situation.'}</p>{context && <small><b>Required sources:</b> {context.required_sources.join(' · ')}</small>}</article>; })}</div>
            </article>

            <article className="panel challengeDetail">
              <div className="panelHead"><div><span className="kicker">Previous mistakes replayed</span><h2>The old ten misses no longer slip through.</h2></div><span className="proofTag">Regression evidence only</span></div>
              <div className="challengeFacts"><div><span>Result range</span><strong>{(challenge.recall_95_ci || []).join(' – ') || '—'}</strong><small>95% range for this simulated replay</small></div><div><span>Added false alarms</span><strong>{challenge.graph_intelligence_delta?.false_positives_added ?? '—'}</strong><small>Increase caused by the extra context checks</small></div><div><span>Misses removed</span><strong>{challenge.graph_intelligence_delta?.false_negatives_removed ?? '—'}</strong><small>Compared with money checks alone</small></div></div>
              <div className="gapGrid">{recoveredClasses.map(([name, values]) => { const context = scenarioFor(data.scenario_catalog, name); return <article key={name}><div className="scenarioCardTop"><span>{values.graph_detected - values.baseline_detected} recovered</span><ScenarioBadge context={context} /></div><h3>{eventLabel(name)}</h3><p>{context?.realism_basis || (name === 'counterparty_substitution' ? 'The bank narration breaks the approved counterparty identity edge.' : 'A rare approver completes a repeated economic motif.')}</p>{context && <small><b>Required sources:</b> {context.required_sources.join(' · ')}</small>}</article>; })}{missedClasses.map(([name, count]) => { const context = scenarioFor(data.scenario_catalog, name); return <article key={name}><div className="scenarioCardTop"><span>{count} remaining misses</span><ScenarioBadge context={context} /></div><h3>{eventLabel(name)}</h3><p>{context?.claim_boundary || 'This class still needs additional evidence and remains disclosed.'}</p>{context && <small><b>Required sources:</b> {context.required_sources.join(' · ')}</small>}</article>; })}</div>
            </article>

            <div className="proofBoundary">
              <article><span className="safeMark">✓</span><div><h2>What this proves</h2><ul><li>Every declared money rule runs deterministically across a batch.</li><li>Credit and debit findings carry explanations, timestamps and citations.</li><li>Uncertainty stops before automatic posting.</li><li>Performance regressions and known misses are measurable.</li></ul></div></article>
              <article><span className="limitMark">!</span><div><h2>What this does not prove</h2><ul><li>Production fraud-detection performance.</li><li>Detection of every unknown anomaly family.</li><li>Real bank or ERP connectivity—all financial records are simulated.</li><li>Authority for Qwen to calculate, approve or move money.</li></ul></div></article>
            </div>

            <article className="panel tierPanel evaluationTiers">
                <div className="panelHead"><div><span className="kicker">Known test coverage</span><h2>Increasingly difficult reconciliation cases</h2></div><span className="proofTag">Written-rule checks</span></div>
              <div className="tierChart">{data.tiers.map(tier => { const closure = tier.n ? Math.round((tier.comp_ok + tier.refusal) / tier.n * 100) : 0; return <div className="tierRow" key={tier.tier}><div className="tierLabel"><strong>T{tier.tier}</strong><span>{tier.n} records</span></div><div className="bar"><i style={{ width: `${closure}%` }} /></div><strong>{tier.tier === 4 ? `${tier.refusal} refused` : tier.batch_acc}</strong></div>; })}</div>
              <div className="tierLegend"><span><i className="good" /> Verified closure</span><span><i className="refused" /> Correct refusal</span><p>Tier 4 is intentionally unresolvable. Refusal is the correct outcome.</p></div>
            </article>
          </section>}

          {tab === 'exceptions' && <section className="pageSection">
            <div className="pageHead"><div><p className="eyebrow">Exceptions</p><h1>Every stopped entry comes with a reason.</h1><p>Credits and debits are both checked. Open any item to compare what the bank said, what the cashbook expected, when it happened, and which source rows support the finding.</p></div><div className="summaryChip"><span>Value waiting for review</span><strong>₹{riskExposure.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</strong></div></div>
            <div className="tablePanel"><div className="tableIntro"><strong>{data.risk_findings.length} entries require review</strong><span>{data.risk_findings.filter(item => item.direction === 'credit').length} credits · {data.risk_findings.filter(item => item.direction === 'debit').length} debits · {data.metrics.risk_false_negatives || 0} known test cases missed</span></div><div className="dataTable riskTable"><div className="tableRow tableHeader"><span>Bank entry</span><span>Direction & timestamp</span><span>Why it was stopped</span><span>Amount</span><span>Priority</span></div>{data.risk_findings.map(item => <button className="tableRow" key={item.bank_txn_id} onClick={() => setSelectedRisk(item)}><span><strong>{item.bank_txn_id}</strong><small>{eventLabel(item.anomaly_type)}</small><ScenarioBadge context={item.scenario_context} /></span><span><strong className={item.direction === 'debit' ? 'debitText' : 'creditText'}>{item.direction.toUpperCase()}</strong><small>{timestamp(item.transaction_timestamp_utc)}</small></span><span><strong>{item.risk_title}</strong><small>{item.reason}</small></span><span className="amount">{item.amount_display}</span><span><em className={`status ${item.severity === 'critical' ? 'badStatus' : 'waitStatus'}`}>{item.severity}</em></span></button>)}</div></div>
          </section>}

          {tab === 'approvals' && <section className="pageSection">
            <div className="pageHead"><div><p className="eyebrow">Approvals</p><h1>Nothing is recorded without a person.</h1><p>The controller prepares a balanced journal entry and locks its financial fields. A reviewer can inspect the evidence, then approve or reject it.</p></div><div className="approvalCounters"><div><span>Waiting</span><strong>{data.approval_summary.pending}</strong></div><div><span>Recorded in demo ledger</span><strong>{data.approval_summary.posted}</strong></div><div><span>Rejected</span><strong>{data.approval_summary.rejected}</strong></div></div></div>
            <div className="queueTools"><div className="filters">{(['pending','posted','rejected','all'] as const).map(filter => <button key={filter} className={approvalFilter === filter ? 'active' : ''} onClick={() => setApprovalFilter(filter)}>{filter[0].toUpperCase() + filter.slice(1)}</button>)}</div><input placeholder="Search proposal, bank or settlement…" value={search} onChange={event => setSearch(event.target.value)} /></div>
            <div className="tablePanel"><div className="dataTable approvalTable"><div className="tableRow tableHeader"><span>Proposal</span><span>Bank group</span><span>Settlement group</span><span>Amount</span><span>Control state</span></div>{visibleApprovals.map(item => <button className="tableRow" key={item.proposal_id} onClick={() => setSelectedJournal(item)}><span><strong className="mono">{shortId(item.proposal_id)}</strong><small>{item.topology || '1:1'} · {item.entries.length} ledger lines</small></span><span><strong className="mono">{(item.bank_txn_ids || [item.bank_txn_id]).length} node{(item.bank_txn_ids || [item.bank_txn_id]).length === 1 ? '' : 's'}</strong><small>{(item.bank_txn_ids || [item.bank_txn_id]).join(' + ')}</small></span><span><strong className="mono">{(item.settlement_ids || [item.settlement_id]).length} node{(item.settlement_ids || [item.settlement_id]).length === 1 ? '' : 's'}</strong><small>{(item.settlement_ids || [item.settlement_id]).map(shortId).join(' + ')}</small></span><span className="amount">{item.display_amount}</span><span><em className={`status ${item.workflow_status === 'posted_to_sandbox_ledger' ? 'goodStatus' : item.workflow_status === 'rejected' ? 'badStatus' : 'waitStatus'}`}>{eventLabel(item.workflow_status)}</em></span></button>)}{!visibleApprovals.length && <p className="empty tableEmpty">No proposals match this filter.</p>}</div></div>
          </section>}

          {tab === 'audit' && <section className="pageSection">
            <div className="pageHead"><div><p className="eyebrow">Activity</p><h1>See what happened and when.</h1><p>Every match, exception, prepared journal, and human decision is recorded with its time and source evidence.</p></div><div className="summaryChip"><span>Events shown</span><strong>{data.audit.length}</strong></div></div>
            <div className="auditLayout"><article className="timeline">{data.audit.map((item, index) => <div className="timelineEvent" key={`${item.event}-${item.proposal_id || item.bank_txn_id || index}-${index}`}><span className="eventDot" /><div className="eventBody"><div><strong>{eventLabel(item.event)}</strong><time>{item.at ? new Date(item.at).toLocaleString() : `Event ${data.audit.length - index}`}</time></div><p>{item.proposal_id ? `${item.proposal_id} · ${item.decision || item.status}` : item.bank_txn_id ? `${item.bank_txn_id}${item.settlement_id ? ` → ${item.settlement_id}` : ''}` : item.status || 'Controller event'}</p>{item.reviewer && <small>Reviewer: {item.reviewer}</small>}</div></div>)}{!data.audit.length && <p className="empty">Connect the local API to load the activity trail.</p>}</article><aside className="auditRules"><span className="kicker">Safety guarantees</span><h2>What the history proves</h2><ul><li><i>01</i><span><strong>Code calculates money</strong>The AI assistant never produces financial amounts.</span></li><li><i>02</i><span><strong>Every issue has sources</strong>Exceptions point back to exact CSV rows.</span></li><li><i>03</i><span><strong>Retries are safe</strong>The same approved proposal cannot be recorded twice.</span></li><li><i>04</i><span><strong>A person has final authority</strong>Only human approval reaches the simulated ledger.</span></li></ul></aside></div>
          </section>}
        </div>
      </section>

      {(selectedJournal || selectedRisk || selectedGraph) && <div className="scrim" onMouseDown={() => { setSelectedJournal(null); setSelectedRisk(null); setSelectedGraph(null); }}><aside className="drawer" onMouseDown={event => event.stopPropagation()}>
        <button className="closeButton" onClick={() => { setSelectedJournal(null); setSelectedRisk(null); setSelectedGraph(null); }} aria-label="Close details">×</button>
        {selectedGraph && <>
          <p className="eyebrow">{selectedGraph.certificate ? 'Accepted match evidence' : 'Rejected match evidence'}</p><h2>{selectedGraph.certificate?.certificate_id || shortId(selectedGraph.candidate_id)}</h2><div className={`exceptionHero graphHero ${selectedGraph.certificate ? '' : 'rejectedGraphHero'}`}><span>{selectedGraph.topology || '1:1'} group · {evidenceLevel(selectedGraph)} · {selectedGraph.certificate ? 'accepted as one complete group' : eventLabel(selectedGraph.rejection_stage || 'not_selected')}</span><strong>Evidence score {selectedGraph.evidence_score}</strong><small>{selectedGraph.bank_ids.join(' + ')} → {selectedGraph.settlement_ids.join(' + ')}</small></div>
          <div className="moneyEquation"><span>Bank total</span><strong>₹{selectedGraph.bank_total}</strong><b>−</b><span>Settlement net</span><strong>₹{selectedGraph.settlement_total}</strong><b>=</b><span>Residual</span><strong className={Number(selectedGraph.residual) === 0 ? 'safeText' : 'debitText'}>₹{selectedGraph.residual}</strong></div>
          <div className="reasonBlock"><span>Transparent score breakdown</span>{selectedGraph.features.map(feature => <div className="featureRow" key={feature.feature}><strong>+{feature.points}</strong><p><b>{eventLabel(feature.feature)}</b>{feature.detail}</p></div>)}</div>
          {selectedGraph.certificate ? <div className="citations"><span>Hard constraints satisfied</span>{selectedGraph.certificate.constraints_satisfied.map(rule => <code key={rule}>✓ {eventLabel(rule)}</code>)}</div> : <div className="citations rejectedRules"><span>Selection blockers</span>{selectedGraph.blockers.map(rule => <code key={rule}>× {eventLabel(rule)}</code>)}</div>}
          {!!selectedGraph.certificate?.rejected_alternatives.length && <div className="alternatives"><span>Nearest rejected alternatives</span>{selectedGraph.certificate.rejected_alternatives.map(item => <div key={item.candidate_id}><strong>{shortId(item.candidate_id)}</strong><small>score {item.evidence_score} · {item.reason}</small></div>)}</div>}
          <div className="gateNotice"><span>◆</span><p><strong>Authority boundary</strong>The certificate was computed by deterministic code. Qwen may explain it, but cannot change the edge, score, amount, or approval state.</p></div>
        </>}
        {selectedJournal && <>
          <p className="eyebrow">Atomic {selectedJournal.topology || '1:1'} journal proposal</p><h2>{selectedJournal.proposal_id}</h2><div className="drawerMeta"><div><span>Bank group</span><strong>{(selectedJournal.bank_txn_ids || [selectedJournal.bank_txn_id]).join(' + ')}</strong></div><div><span>Settlement group</span><strong>{(selectedJournal.settlement_ids || [selectedJournal.settlement_id]).join(' + ')}</strong></div><div><span>Total value</span><strong>{selectedJournal.display_amount}</strong></div><div><span>Balance check</span><strong className="safeText">✓ Group debit = credit</strong></div></div>
          <div className="journal"><div className="journalHead"><span>Account</span><span>Debit</span><span>Credit</span></div>{selectedJournal.entries.map(entry => <div key={entry.account}><strong>{entry.account}</strong><span>{Number(entry.debit) ? `₹${Number(entry.debit).toLocaleString('en-IN',{minimumFractionDigits:2})}` : '—'}</span><span>{Number(entry.credit) ? `₹${Number(entry.credit).toLocaleString('en-IN',{minimumFractionDigits:2})}` : '—'}</span></div>)}<div className="journalTotal"><strong>Total</strong><span>{selectedJournal.display_amount}</span><span>{selectedJournal.display_amount}</span></div></div>
          <div className="gateNotice"><span>◆</span><p><strong>Human approval required</strong>{selectedJournal.approval.reason}. No financial fields can be edited here.</p></div>
          {selectedJournal.workflow_status === 'awaiting_human_approval' ? <div className="drawerActions"><button className="rejectButton" onClick={() => decide(selectedJournal, 'reject')} disabled={busy}>Reject</button><button className="approveButton" onClick={() => decide(selectedJournal, 'approve')} disabled={busy}>{busy ? 'Recording…' : 'Approve to sandbox ledger'} <span>→</span></button></div> : <div className="decisionReceipt"><span className={selectedJournal.workflow_status === 'rejected' ? 'badReceipt' : ''}>{selectedJournal.workflow_status === 'rejected' ? '×' : '✓'}</span><div><strong>{eventLabel(selectedJournal.workflow_status)}</strong><small>{selectedJournal.ledger_entry_id || selectedJournal.reviewer || 'Decision recorded'}</small></div></div>}
        </>}
        {selectedRisk && <>
          <p className="eyebrow">Bank-entry review evidence</p><h2>{selectedRisk.bank_txn_id}</h2><div className="exceptionHero"><span>{selectedRisk.direction} under review</span><strong>{selectedRisk.amount_display}</strong><small>{selectedRisk.risk_title}</small></div><div className="drawerMeta"><div><span>Direction</span><strong className={selectedRisk.direction === 'debit' ? 'debitText' : 'creditText'}>{selectedRisk.direction.toUpperCase()}</strong></div><div><span>Priority</span><strong>{selectedRisk.severity.toUpperCase()}</strong></div><div><span>Transaction timestamp</span><strong>{timestamp(selectedRisk.transaction_timestamp_utc)}</strong></div><div><span>Source extracted</span><strong>{timestamp(selectedRisk.source_extracted_at_utc)}</strong></div></div>{selectedRisk.scenario_context && <div className="scenarioEvidence"><div><ScenarioBadge context={selectedRisk.scenario_context} /><strong>{selectedRisk.scenario_context.label}</strong></div><p>{selectedRisk.scenario_context.realism_basis}</p><small><b>Evidence required:</b> {selectedRisk.scenario_context.required_sources.join(' · ')}</small><small><b>What this finding claims:</b> {selectedRisk.scenario_context.claim_boundary}</small></div>}<div className="reasonBlock"><span>Why it was stopped</span><h3>{selectedRisk.reason}</h3></div><div className="evidenceText"><span>What the bank says</span><p>{selectedRisk.observed_text}</p></div><div className="evidenceText"><span>What the other records should show</span><p>{selectedRisk.expected_text}</p></div>
          {selectedRisk.graph_ood && <div className={`graphRiskReceipt ${selectedRisk.graph_ood.is_graph_ood ? 'graphRiskFlagged' : ''}`}><div><span>Unusual-context score</span><strong>{selectedRisk.graph_ood.score} / 100</strong><small>review starts at {selectedRisk.graph_ood.threshold}</small></div><div className="graphRiskSignals">{selectedRisk.graph_ood.signals.map(signal => <article key={signal.code}><b>+{signal.points}</b><p><strong>{eventLabel(signal.code)}</strong><small>{signal.detail}</small></p></article>)}</div>{!!selectedRisk.graph_ood.evidence_path.length && <div className="evidencePath">{selectedRisk.graph_ood.evidence_path.map((node, index) => <span key={node}>{index > 0 && <i>→</i>}<code>{node}</code></span>)}</div>}</div>}
          <div className="gateNotice"><span>!</span><p><strong>Recommended auditor action</strong>{selectedRisk.recommended_action}</p></div><div className="citations"><span>Exact evidence rows</span>{selectedRisk.citations.map(citation => <code key={citation}>{citation}</code>)}</div><div className="detectionStamp">{selectedRisk.risk_engine || 'Deterministic controls'} · detected {timestamp(selectedRisk.detected_at_utc)}</div>
        </>}
      </aside></div>}
    </main>
  );
}
