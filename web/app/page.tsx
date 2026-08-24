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
  solver?: string; selection_threshold?: number; bank_node_count: number; settlement_node_count: number;
  candidate_count: number; selectable_candidate_count: number; selected_candidate_count: number;
  abstained_bank_count: number; rejected_candidate_count: number; money_conflict_count: number;
  contested_bank_count: number; global_constraints: string[]; selected_edges: GraphEdge[];
  candidate_topology_counts?: Record<string, number>; selected_topology_counts?: Record<string, number>;
  hard_gate_rejected_topology_counts?: Record<string, number>; global_rejected_topology_counts?: Record<string, number>;
  timing_policy?: { policy_label: string; scope_note: string; cycle_counts: Record<string, number>; chronology_violations: number; thursday_t2_example?: { settlement_id: string; capture_date: string; settled_at: string; working_day_path: string } | null };
  rejected_examples: GraphEdge[]; contested_groups: ContestedGroup[];
  mesh: MeshData;
};
type Overview = {
  generated_at: string | null;
  runtime: { orchestrator: string; money_engine: string; language_model: string; ledger: string; mode: string };
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
    { step: '02', name: 'Reconcile', note: 'LedgerGraph global solve', status: 'complete' },
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
  { id: 'overview', label: 'Judge overview', key: '⌁' },
  { id: 'ledgergraph', label: 'LedgerGraph', key: '◇' },
  { id: 'evaluation', label: 'Evaluation proof', key: '◎' },
  { id: 'exceptions', label: 'Risk review', key: '!' },
  { id: 'approvals', label: 'Approval queue', key: '✓' },
  { id: 'audit', label: 'Audit trail', key: '≡' },
] as const;
const topologyScenarioIds = ['topology:1:1', 'topology:1:N', 'topology:N:1', 'topology:N:M'] as const;
type Tab = typeof tabs[number]['id'];

function eventLabel(event: string): string {
  return event.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase());
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
  if (features.has('full_utr_exact') && features.has('signed_amount_exact')) return 'L0 exact';
  if (features.has('signed_amount_exact')) return 'L1 structured';
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
    ['Dubious entries stopped', data.risk_findings.length, `${data.risk_findings.filter(item => item.direction === 'credit').length} credits · ${data.risk_findings.filter(item => item.direction === 'debit').length} debits`, 'mint'],
    ['Safe journal proposals', data.approval_summary.total, '0 automatically posted', 'mint'],
    ['Fresh fraud holdout', `${fraudHoldout.recall || '—'} recall`, `${fraudHoldout.false_negatives ?? '—'} honest misses · detector frozen`, 'plain'],
  ];
  const riskExposure = data.risk_findings.reduce((total, item) => total + Number(item.amount || 0), 0);

  return (
    <main className="appShell">
      <aside className="sidebar">
        <div className="brand"><span className="brandMark">FC</span><div><strong>Finance Controller</strong><small>Settlement control room</small></div></div>
        <nav aria-label="Primary navigation">
          {tabs.map(item => <button key={item.id} onClick={() => setTab(item.id)} className={tab === item.id ? 'active' : ''}><span>{item.key}</span>{item.label}{item.id === 'exceptions' && <em>{data.risk_findings.length}</em>}{item.id === 'approvals' && <em>{data.approval_summary.pending}</em>}</button>)}
        </nav>
        <div className="authorityCard">
          <span className="authorityIcon">◆</span><div><strong>Authority boundary</strong><p>The model can explain evidence. It cannot calculate, approve, or post money.</p></div>
        </div>
        <div className="runtimeStack">
          <span>Runtime</span><strong>{data.runtime.orchestrator}</strong><small>{data.runtime.money_engine}</small><small>{data.runtime.language_model}</small>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div><span className={`connection ${connection}`}><i /> {connection === 'live' ? 'Local controller online' : connection === 'connecting' ? 'Connecting to controller' : 'Committed snapshot'}</span></div>
          <div className="topActions"><span className="seed">SIMULATED DATA ONLY</span><button className="runButton" onClick={runPipeline} disabled={busy || connection !== 'live'}>{busy ? 'Running…' : 'Run current batch'} <b>→</b></button></div>
        </header>

        <div className="content">
          {tab === 'overview' && <>
            <section className="hero">
              <div><p className="eyebrow">The 20-second explanation</p><h1>Reconcile settlements.<br /><span>Stop uncertain money.</span></h1><p className="lede">Deterministic code checks Razorpay, bank, and ERP evidence across the whole batch. Qwen explains the result; only a human can approve an uneditable journal.</p></div>
              <div className="batchStamp"><span>Simulation-only batch</span><strong>{data.headline.bank_entries} entries</strong><small>{data.risk_findings.length} dubious · {data.approval_summary.total} safe proposals · 0 auto-posted</small><small>Extracted {timestamp(data.provenance.extracted_at_utc)}</small></div>
            </section>

            <section className="judgeThesis">
              <strong>The problem</strong><p>Finance teams manually compare payment-gateway settlements, bank credits, and accounting records. A match can still hide an unsupported component.</p>
              <strong>The answer</strong><p>This controller closes only explainable money, exposes every exception with row-level evidence, and fails closed before anything reaches the sandbox ledger.</p>
            </section>

            <section className="provenanceBar" aria-label="Data and run timestamps">
              <article><span>Extraction timestamp</span><strong>{timestamp(data.provenance.extracted_at_utc)}</strong><small>{data.provenance.dataset_id || 'Synthetic source bundle'}</small></article>
              <article><span>Data coverage window</span><strong>{data.provenance.coverage_start || '—'} → {data.provenance.coverage_end || '—'}</strong><small>Timezone: {data.provenance.timezone || 'UTC'}</small></article>
              <article><span>Pipeline completed</span><strong>{timestamp(data.provenance.run_completed_at_utc || data.generated_at)}</strong><small>Started {timestamp(data.provenance.run_started_at_utc)}</small></article>
              <article><span>Known-miss control replay</span><strong>{challenge.baseline_without_graph?.recall || '—'} → {challenge.recall || '—'}</strong><small>{challenge.graph_intelligence_delta?.additional_true_positives || 0} recovered · fresh holdout reported separately</small></article>
            </section>

            <section className="stageRail" aria-label="Pipeline stages">
              {data.stages.map((stage, index) => <article className={`stage ${stage.status}`} key={stage.name}><div className="stageTop"><span>{stage.step}</span><i /></div><strong>{stage.name}</strong><small>{stage.note}</small>{index < data.stages.length - 1 && <b className="connector">→</b>}</article>)}
            </section>

            <section className="metricGrid">{metricCards.map(([label, value, note, tone]) => <article key={label} className={tone === 'mint' ? 'metricMint' : ''}><span>{label}</span><strong>{value}</strong><small>{note}</small></article>)}</section>

            <section className="realityPanel" aria-label="Synthetic scenario realism legend">
              <div className="realityIntro"><div><span className="kicker">Read the synthetic data correctly</span><h2>Possible does not mean equally common—or visible from Razorpay alone.</h2></div><p>{data.scenario_catalog.frequency_boundary || 'Scenario counts measure test coverage, not real-world prevalence.'}</p></div>
              <div className="realityGrid">{data.scenario_catalog.categories.map(category => <article key={category.id}><span className={`scenarioBadge scenario-${category.id}`}>{category.short_label}</span><p>{category.description}</p><small>{category.examples.join(' · ')}</small></article>)}</div>
              <div className="realitySources"><strong>Realism basis:</strong><span>official settlement/report mechanics plus explicitly synthetic cross-system and ERP stress cases.</span>{(data.scenario_catalog.references || []).map(reference => <a key={reference.url} href={reference.url} target="_blank" rel="noreferrer">{reference.label} ↗</a>)}</div>
            </section>

            <section className="overviewGrid">
              <article className="panel tierPanel">
                <div className="panelHead"><div><span className="kicker">System in one picture</span><h2>Three sources. One bounded controller.</h2></div><button className="textButton" onClick={() => setTab('ledgergraph')}>Understand L0 / L1 →</button></div>
                <div className="systemMap">
                  <div className="sourceStack"><article><i>RZP</i><span><strong>Razorpay Test Mode</strong><small>Simulated payments and settlement components</small></span></article><article><i>BNK</i><span><strong>Simulated bank</strong><small>Credits, debits, narrations and balances</small></span></article><article><i>ERP</i><span><strong>Simulated merchant ERP</strong><small>Approved cashbook evidence</small></span></article></div>
                  <div className="mapArrow">→</div>
                  <article className="controllerCore"><span>Deterministic authority</span><strong>Match · calculate · verify</strong><small>Decimal arithmetic, exact rules, stopping thresholds</small></article>
                  <div className="mapArrow">→</div>
                  <div className="outputStack"><article><strong>72</strong><small>safe proposals</small></article><article><strong>{data.risk_findings.length}</strong><small>dubious holds</small></article><article><strong>0</strong><small>auto-posted</small></article></div>
                </div>
                <div className="modelBoundary"><strong>Qwen’s only job:</strong><span>turn retrieved evidence into a readable answer. It never selects a match, calculates money, approves, or posts.</span></div>
              </article>

              <article className="panel reviewPanel">
                <div className="panelHead"><div><span className="kicker">Needs attention</span><h2>{data.risk_findings.length} dubious entries</h2></div><button className="textButton" onClick={() => setTab('exceptions')}>Open queue →</button></div>
                <div className="reviewList">{data.risk_findings.slice(0, 4).map(item => <button key={item.bank_txn_id} onClick={() => setSelectedRisk(item)}><span className="warningDot">!</span><div><strong>{item.bank_txn_id} · {item.direction}</strong><small>{item.risk_title}</small><ScenarioBadge context={item.scenario_context} /></div><b>{item.amount_display}</b></button>)}{!data.risk_findings.length && <p className="empty">No dubious bank entries were detected.</p>}</div>
              </article>

              <article className="panel evidencePanel">
                <div className="panelHead"><div><span className="kicker">Settlement Q&A</span><h2>Ask the evidence, not the model</h2></div><label className="modelToggle"><input type="checkbox" checked={useModel} onChange={event => setUseModel(event.target.checked)} /><span />HF Qwen explanation</label></div>
                <form onSubmit={ask} className="askForm"><input value={question} onChange={event => setQuestion(event.target.value)} aria-label="Ask a settlement question" /><button disabled={asking || connection !== 'live'}>{asking ? 'Checking…' : 'Ask'} <span>↗</span></button></form>
                <div className={`answer ${answer ? 'hasAnswer' : ''}`}>{answer || <><span className="answerMark">i</span><p>Identifiers and known finance intents route through deterministic read-only tools. Qwen receives only the resulting evidence object.</p></>}</div>
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
            <div className="pageHead"><div><p className="eyebrow">Global constraint reconciliation</p><h1>Every rupee forms a graph.</h1><p>LedgerGraph proposes fuzzy candidates, then deterministically solves the whole batch under exact signed-money and one-use constraints. Ambiguity becomes an abstention—not a guess.</p></div><div className="summaryChip"><span>Held-out cases exact</span><strong>{data.ledgergraph_eval.held_out_ledgergraph?.cases_exactly_correct || '—'}/{data.ledgergraph_eval.held_out_case_count || '—'}</strong><small>{data.ledgergraph_eval.held_out_ledgergraph?.false_selections || 0} false selections · threshold frozen on 4 calibration cases</small></div></div>

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

            <div className="graphStats"><article><span>Money nodes</span><strong>{data.ledgergraph.bank_node_count + data.ledgergraph.settlement_node_count}</strong><small>{data.ledgergraph.bank_node_count} bank · {data.ledgergraph.settlement_node_count} settlement</small></article><article><span>Candidate edges</span><strong>{data.ledgergraph.candidate_count}</strong><small>{data.ledgergraph.contested_bank_count} bank nodes had competing hypotheses</small></article><article><span>Rejected edges</span><strong>{data.ledgergraph.rejected_candidate_count}</strong><small>{Object.values(data.ledgergraph.hard_gate_rejected_topology_counts || {}).reduce((sum, value) => sum + value, 0)} hard gate · {Object.values(data.ledgergraph.global_rejected_topology_counts || {}).reduce((sum, value) => sum + value, 0)} global conflict</small></article><article><span>Globally selected</span><strong>{data.ledgergraph.selected_candidate_count}</strong><small>₹0 residual · each node used once</small></article></div>

            <article className="panel graphCanvas">
              <div className="panelHead graphPanelHead"><div><span className="kicker">Inspectable batch proof</span><h2>{graphMode === 'candidates' ? 'The candidate field before optimization' : 'The globally consistent solution'}</h2></div><div className="graphModeSwitch"><button className={graphMode === 'candidates' ? 'active' : ''} onClick={() => setGraphMode('candidates')}>Before · {data.ledgergraph.candidate_count} candidates</button><button className={graphMode === 'solution' ? 'active' : ''} onClick={() => setGraphMode('solution')}>After · {data.ledgergraph.selected_candidate_count} selected</button></div></div>
              <div className="candidateLegend"><span><i className="bankCircle" /> bank node</span><span><i className="settlementCircle" /> settlement node</span><span><i className="groupCircle" /> atomic group</span><span><i className="selectedLine" /> selected path</span><span><i className="rejectedLine" /> rejected candidate</span><p>{graphMode === 'candidates' ? 'All candidate paths are visible simultaneously. A centre group circle means the connected nodes must be accepted or rejected together.' : 'Every topology is present: direct, aggregated, split, and many-to-many netted groups.'}</p></div>
              <LedgerMesh mesh={data.ledgergraph.mesh} mode={graphMode} onSelectEdge={edge => setSelectedGraph(edge as GraphEdge)} />
            </article>

            <article className="panel evidenceLadderPanel">
              <div className="panelHead"><div><span className="kicker">Candidate evidence ladder</span><h2>What L0 and L1 actually check</h2></div><span className="proofTag">Evidence first · decision later</span></div>
              <p className="ladderIntro">L0 and L1 describe increasingly tolerant ways to create and score one-to-one hypotheses. Neither may relax the amount invariant, and neither gets the final word: LedgerGraph resolves collisions across the complete batch.</p>
              <div className="evidenceLadder">
                <article className="l0Card"><div className="levelBadge">L0</div><span>Exact evidence</span><h3>Full UTR + exact signed net</h3><ul><li>The complete settlement UTR must appear in the bank narration.</li><li>Bank credit minus debit must exactly equal settlement net.</li><li>Multiple exact candidates still fail closed.</li></ul><div className="scoreFormula"><b>+100</b> full UTR <i>+</i> <b>+50</b> money</div></article>
                <div className="ladderArrow">→</div>
                <article className="l1Card"><div className="levelBadge">L1</div><span>Structured evidence</span><h3>Exact money + corroboration</h3><ul><li>Exact signed net remains mandatory.</li><li>Date agreement or a bounded posting window adds evidence.</li><li>Normalized UTR, prefix, or edit distance ≤ 2 can rank candidates.</li></ul><div className="scoreFormula"><b>≥65</b> selectable threshold</div></article>
                <div className="ladderArrow">→</div>
                <article className="globalCard"><div className="levelBadge">G</div><span>Global decision</span><h3>Whole-batch hypergraph solve</h3><ul><li>Each bank and settlement node can be used once.</li><li>1:1, 1:N, N:1 and bounded N:M groups are atomic selections.</li><li>Reducible group wrappers, tied optima and exhausted search fail closed.</li></ul><div className="scoreFormula"><b>₹0</b> required group residual</div></article>
              </div>
              <div className="legacyClarifier"><strong>Important naming note</strong><p><code>l0_exact.py</code> and <code>l1_search.py</code> are retained as transparent evaluation baselines. The production controller does not run them greedily in sequence; LedgerGraph incorporates their evidence families, adds controlled fuzzy and grouped candidates, and decides globally.</p></div>
            </article>

            <article className="panel intelligencePanel">
              <div className="panelHead"><div><span className="kicker">GraphShield · relational open-set risk</span><h2>Balanced does not automatically mean safe.</h2></div><span className="proofTag">Review signal only · no LLM labels</span></div>
              <p className="intelligenceIntro">After LedgerGraph establishes the accounting explanation, GraphShield inspects the surrounding identity and approval subgraph. It cannot rewrite a match or amount; it can only stop an unfamiliar evidence path for human review.</p>
              <div className="intelligenceFlow">
                <article><span>01 · Reconcile</span><strong>LedgerGraph</strong><small>Who paid what? Exact money and global one-use constraints.</small></article><b>→</b><article><span>02 · Inspect behavior</span><strong>GraphShield</strong><small>Does this identity, approver, or repeated motif belong here?</small></article><b>→</b><article><span>03 · Bound authority</span><strong>Human review</strong><small>Novel paths stop. Neither graph layer can post money.</small></article>
              </div>
              <div className="oodDelta">
                <div className="deltaMetric baselineMetric"><span>Exact controls only</span><strong>{graphIntel.challenge_baseline?.recall || '—'}</strong><small>{graphIntel.challenge_baseline?.false_negatives ?? '—'} missed synthetic frauds</small></div>
                <div className="deltaArrow"><span>+{graphIntel.challenge_delta?.additional_true_positives ?? '—'} recovered</span><b>→</b><small>{graphIntel.challenge_delta?.false_positives_added ?? '—'} added false positives</small></div>
                <div className="deltaMetric enhancedMetric"><span>Known replay with GraphShield</span><strong>{graphIntel.challenge_enhanced?.recall || '—'}</strong><small>{graphIntel.challenge_enhanced?.false_negatives ?? '—'} misses · precision {graphIntel.challenge_enhanced?.precision || '—'}</small></div>
              </div>
              <div className="graphSignalGrid">
                <article><i>ID</i><div><span>Identity edge disagreement</span><strong>Approved counterparty ≠ observed beneficiary</strong><small>Token coverage is measured on the linked bank → reference → cashbook → counterparty path.</small></div></article>
                <article><i>AP</i><div><span>Novel approval motif</span><strong>Rare approver + repeated economics</strong><small>A new approver backing a repeated direction, amount and counterparty pattern crosses the review threshold.</small></div></article>
                <article><i>RF</i><div><span>Reference topology</span><strong>Orphans and unexpected fan-out</strong><small>Missing event links or one reference touching multiple bank nodes become explainable graph signals.</small></div></article>
              </div>
              <div className="intelligenceBoundary"><strong>What the result means</strong><p>The known-miss replay improves from {graphIntel.challenge_baseline?.recall || '—'} to {graphIntel.challenge_enhanced?.recall || '—'}, but it is a control replay—not validation. The separately frozen fraud holdout scores {graphIntel.fresh_holdout?.recall || '—'} recall with {graphIntel.fresh_holdout?.false_negatives ?? '—'} disclosed misses, showing the current temporal and aggregate blind spots.</p></div>
            </article>

            <div className="graphProofGrid">
              <article className="panel"><div className="panelHead"><div><span className="kicker">Why it is stronger</span><h2>Hard constraints after soft evidence</h2></div></div><ol className="constraintList"><li><b>01</b><span><strong>Generate candidates</strong>Exact amount, dates, UTRs and bounded edit distance contribute transparent points.</span></li><li><b>02</b><span><strong>Solve globally</strong>All links compete in one deterministic optimization, removing row-order dependence.</span></li><li><b>03</b><span><strong>Prove or abstain</strong>Money must conserve exactly; tied optima and exhausted search fail closed.</span></li></ol></article>
              <article className="panel"><div className="panelHead"><div><span className="kicker">Measured delta</span><h2>Same adversarial suite, three systems</h2></div><span className="proofTag">4 calibration · 7 held-out</span></div><div className="comparisonList">{(data.ledgergraph_eval.comparison || []).map(item => <div key={item.system} className={item.system === 'ledgergraph_global' ? 'winner' : ''}><span>{eventLabel(item.system)}</span><strong>{item.cases_exactly_correct}/{item.case_count}</strong><small>{item.hypothesis_recall} recall · {item.false_selections} false</small></div>)}</div><p className="scopeNote">Threshold 65 was chosen on the calibration partition; the held-out partition scores {data.ledgergraph_eval.held_out_ledgergraph?.cases_exactly_correct || '—'}/{data.ledgergraph_eval.held_out_case_count || '—'} with zero false selections. This remains synthetic reconciliation evidence—not production fraud performance.</p></article>
            </div>

            <article className="panel scenarioPanel"><div className="panelHead"><div><span className="kicker">Failure modes made visible</span><h2>Adversarial scenario ledger</h2></div><span className="proofTag">1:1 · 1:N · N:1 · N:M · abstention</span></div><div className="scenarioGrid">{(data.ledgergraph_eval.cases || []).map(item => <article key={item.case_id}><span>{item.partition === 'held_out' ? 'HELD-OUT' : 'CALIBRATION'} · {item.ledgergraph_global.exact ? '✓ safe' : '! review'}</span><h3>{eventLabel(item.case_id)}</h3><p>{item.claim}</p><small>{item.ledgergraph_candidate_count} candidates · {item.ledgergraph_abstained_banks.length} abstained bank nodes</small></article>)}</div></article>
          </section>}

          {tab === 'evaluation' && <section className="pageSection evaluationPage">
            <div className="pageHead"><div><p className="eyebrow">What the numbers actually mean</p><h1>Proof without the 100% illusion.</h1><p>Known-rule conformance, the known-miss replay, and the post-freeze fraud holdout are reported separately. The detector is never tuned against the fresh partition.</p></div><div className="summaryChip challengeChip"><span>Fresh post-freeze holdout</span><strong>{fraudHoldout.recall || '—'} recall</strong><small>{fraudHoldout.false_negatives ?? '—'} honest misses · {fraudHoldout.specificity || '—'} specificity</small></div></div>

            <div className="evaluationDefinitions">
              <article><span>Closed-world conformance</span><strong>“Did we implement the declared controls correctly?”</strong><p>The detector and benchmark share known anomaly families. A perfect result is expected and is treated as a regression check—not generalization.</p></article>
              <article><span>Known-miss mutation replay</span><strong>“Do the added relational controls prevent known regressions?”</strong><p>GraphShield was designed after these misses were analysed. The before/after score is a regression control only; generalization is measured separately by the post-freeze holdout.</p></article>
              <article><span>Post-freeze fraud holdout</span><strong>“What does the unchanged detector miss on new families?”</strong><p>The detector source hash is locked before temporal, aggregate, and control-plane mutations run. Misses remain visible and no signal is added in response.</p></article>
            </div>

            <div className="evalLayerGrid">
              <article className="evalCard"><span className="evalIndex">01 · Frozen fixture</span><strong>{data.metrics.risk_recall || '—'}</strong><h2>Closed-world conformance</h2><p>{data.risk_summary.records || data.headline.bank_entries} bank entries · {data.risk_summary.dubious_records || data.risk_findings.length} dubious · both credit and debit</p><em className="goodStatus">Rules implemented</em></article>
              <article className="evalCard"><span className="evalIndex">02 · Varied seeds</span><strong>{data.robustness.risk_recall || '—'}</strong><h2>Multi-seed conformance</h2><p>{data.robustness.bank_entries || 0} entries · {data.robustness.seed_count || 0} seeds · {data.robustness.false_auto_closures || 0} false auto-closures</p><em className="goodStatus">Regression stable</em></article>
              <article className="evalCard challengeCard"><span className="evalIndex">03 · Post-generation mutations</span><strong>{challenge.baseline_without_graph?.recall || '—'} → {challenge.recall || '—'}</strong><h2>Graph intelligence delta</h2><p>{challenge.graph_intelligence_delta?.additional_true_positives || 0} additional detections · {challenge.graph_intelligence_delta?.false_positives_added || 0} added false positives · 440 entries</p><em className="waitStatus">Synthetic replay, not production proof</em></article>
              <article className="evalCard holdoutCard"><span className="evalIndex">04 · Detector frozen first</span><strong>{fraudHoldout.recall || '—'}</strong><h2>Fresh fraud-family holdout</h2><p>{fraudHoldout.holdout_positive_records || 0} dubious · {fraudHoldout.holdout_negative_records || 0} clean controls · {fraudHoldout.false_negatives || 0} disclosed misses</p><em className="badStatus">Blind spots measured</em></article>
            </div>

            <article className="panel challengeDetail holdoutDetail">
              <div className="panelHead"><div><span className="kicker">Hash-locked before evaluation</span><h2>The fresh partition breaks the 100% story.</h2></div><span className="proofTag">{fraudHoldout.detector_version || 'Detector freeze pending'}</span></div>
              <div className="challengeFacts"><div><span>Fresh recall interval</span><strong>{(fraudHoldout.recall_95_ci || []).join(' – ') || '—'}</strong><small>Synthetic Wilson interval only</small></div><div><span>Fresh false positives</span><strong>{fraudHoldout.false_positives ?? '—'}</strong><small>Across frozen clean controls</small></div><div><span>Detector fingerprint</span><strong>{fraudHoldout.detector_sha256 ? shortId(fraudHoldout.detector_sha256) : '—'}</strong><small>A source change invalidates this partition</small></div></div>
              <div className="gapGrid">{Object.entries(fraudHoldout.missed_classes || {}).map(([name, count]) => { const context = scenarioFor(data.scenario_catalog, name); return <article key={name}><div className="scenarioCardTop"><span>{count} fresh misses</span><ScenarioBadge context={context} /></div><h3>{eventLabel(name)}</h3><p>{context?.realism_basis || 'Current GraphShield lacks the evidence required for this synthetic family.'}</p>{context && <small><b>Required sources:</b> {context.required_sources.join(' · ')}</small>}</article>; })}</div>
            </article>

            <article className="panel challengeDetail">
              <div className="panelHead"><div><span className="kicker">Known-miss control replay</span><h2>The old ten misses became relational graph signals.</h2></div><span className="proofTag">Regression evidence, not validation</span></div>
              <div className="challengeFacts"><div><span>Enhanced recall interval</span><strong>{(challenge.recall_95_ci || []).join(' – ') || '—'}</strong><small>Wilson 95% interval for this synthetic replay</small></div><div><span>Added false alarms</span><strong>{challenge.graph_intelligence_delta?.false_positives_added ?? '—'}</strong><small>Increment caused by GraphShield</small></div><div><span>False negatives removed</span><strong>{challenge.graph_intelligence_delta?.false_negatives_removed ?? '—'}</strong><small>Relative to exact deterministic controls</small></div></div>
              <div className="gapGrid">{recoveredClasses.map(([name, values]) => { const context = scenarioFor(data.scenario_catalog, name); return <article key={name}><div className="scenarioCardTop"><span>{values.graph_detected - values.baseline_detected} recovered</span><ScenarioBadge context={context} /></div><h3>{eventLabel(name)}</h3><p>{context?.realism_basis || (name === 'counterparty_substitution' ? 'The bank narration breaks the approved counterparty identity edge.' : 'A rare approver completes a repeated economic motif.')}</p>{context && <small><b>Required sources:</b> {context.required_sources.join(' · ')}</small>}</article>; })}{missedClasses.map(([name, count]) => { const context = scenarioFor(data.scenario_catalog, name); return <article key={name}><div className="scenarioCardTop"><span>{count} remaining misses</span><ScenarioBadge context={context} /></div><h3>{eventLabel(name)}</h3><p>{context?.claim_boundary || 'This class still needs additional evidence and remains disclosed.'}</p>{context && <small><b>Required sources:</b> {context.required_sources.join(' · ')}</small>}</article>; })}</div>
            </article>

            <div className="proofBoundary">
              <article><span className="safeMark">✓</span><div><h2>What this proves</h2><ul><li>Every declared money rule runs deterministically across a batch.</li><li>Credit and debit findings carry explanations, timestamps and citations.</li><li>Uncertainty stops before automatic posting.</li><li>Performance regressions and known misses are measurable.</li></ul></div></article>
              <article><span className="limitMark">!</span><div><h2>What this does not prove</h2><ul><li>Production fraud-detection performance.</li><li>Detection of every unknown anomaly family.</li><li>Real bank or ERP connectivity—all financial records are simulated.</li><li>Authority for Qwen to calculate, approve or move money.</li></ul></div></article>
            </div>

            <article className="panel tierPanel evaluationTiers">
              <div className="panelHead"><div><span className="kicker">Declared fixture coverage</span><h2>Difficulty tiers inside the closed world</h2></div><span className="proofTag">Conformance only</span></div>
              <div className="tierChart">{data.tiers.map(tier => { const closure = tier.n ? Math.round((tier.comp_ok + tier.refusal) / tier.n * 100) : 0; return <div className="tierRow" key={tier.tier}><div className="tierLabel"><strong>T{tier.tier}</strong><span>{tier.n} records</span></div><div className="bar"><i style={{ width: `${closure}%` }} /></div><strong>{tier.tier === 4 ? `${tier.refusal} refused` : tier.batch_acc}</strong></div>; })}</div>
              <div className="tierLegend"><span><i className="good" /> Verified closure</span><span><i className="refused" /> Correct refusal</span><p>Tier 4 is intentionally unresolvable. Refusal is the correct outcome.</p></div>
            </article>
          </section>}

          {tab === 'exceptions' && <section className="pageSection">
            <div className="pageHead"><div><p className="eyebrow">Bidirectional bank controls</p><h1>Dubious means explainable.</h1><p>Every credit and debit is checked against independent evidence, with observed text, expected text, timestamps, and exact source rows.</p></div><div className="summaryChip"><span>Value under review</span><strong>₹{riskExposure.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</strong></div></div>
            <div className="tablePanel"><div className="tableIntro"><strong>{data.risk_findings.length} entries require review</strong><span>{data.risk_findings.filter(item => item.direction === 'credit').length} credits · {data.risk_findings.filter(item => item.direction === 'debit').length} debits · {data.metrics.risk_false_negatives || 0} missed</span></div><div className="dataTable riskTable"><div className="tableRow tableHeader"><span>Bank entry</span><span>Direction & timestamp</span><span>Why it is dubious</span><span>Amount</span><span>Severity</span></div>{data.risk_findings.map(item => <button className="tableRow" key={item.bank_txn_id} onClick={() => setSelectedRisk(item)}><span><strong>{item.bank_txn_id}</strong><small>{eventLabel(item.anomaly_type)}</small><ScenarioBadge context={item.scenario_context} /></span><span><strong className={item.direction === 'debit' ? 'debitText' : 'creditText'}>{item.direction.toUpperCase()}</strong><small>{timestamp(item.transaction_timestamp_utc)}</small></span><span><strong>{item.risk_title}</strong><small>{item.reason}</small></span><span className="amount">{item.amount_display}</span><span><em className={`status ${item.severity === 'critical' ? 'badStatus' : 'waitStatus'}`}>{item.severity}</em></span></button>)}</div></div>
          </section>}

          {tab === 'approvals' && <section className="pageSection">
            <div className="pageHead"><div><p className="eyebrow">Human-in-the-loop</p><h1>Nothing posts itself.</h1><p>LangGraph pauses at a durable interrupt. Financial fields are read-only; a reviewer may only approve or reject.</p></div><div className="approvalCounters"><div><span>Pending</span><strong>{data.approval_summary.pending}</strong></div><div><span>Sandbox posted</span><strong>{data.approval_summary.posted}</strong></div><div><span>Rejected</span><strong>{data.approval_summary.rejected}</strong></div></div></div>
            <div className="queueTools"><div className="filters">{(['pending','posted','rejected','all'] as const).map(filter => <button key={filter} className={approvalFilter === filter ? 'active' : ''} onClick={() => setApprovalFilter(filter)}>{filter[0].toUpperCase() + filter.slice(1)}</button>)}</div><input placeholder="Search proposal, bank or settlement…" value={search} onChange={event => setSearch(event.target.value)} /></div>
            <div className="tablePanel"><div className="dataTable approvalTable"><div className="tableRow tableHeader"><span>Proposal</span><span>Bank group</span><span>Settlement group</span><span>Amount</span><span>Control state</span></div>{visibleApprovals.map(item => <button className="tableRow" key={item.proposal_id} onClick={() => setSelectedJournal(item)}><span><strong className="mono">{shortId(item.proposal_id)}</strong><small>{item.topology || '1:1'} · {item.entries.length} ledger lines</small></span><span><strong className="mono">{(item.bank_txn_ids || [item.bank_txn_id]).length} node{(item.bank_txn_ids || [item.bank_txn_id]).length === 1 ? '' : 's'}</strong><small>{(item.bank_txn_ids || [item.bank_txn_id]).join(' + ')}</small></span><span><strong className="mono">{(item.settlement_ids || [item.settlement_id]).length} node{(item.settlement_ids || [item.settlement_id]).length === 1 ? '' : 's'}</strong><small>{(item.settlement_ids || [item.settlement_id]).map(shortId).join(' + ')}</small></span><span className="amount">{item.display_amount}</span><span><em className={`status ${item.workflow_status === 'posted_to_sandbox_ledger' ? 'goodStatus' : item.workflow_status === 'rejected' ? 'badStatus' : 'waitStatus'}`}>{eventLabel(item.workflow_status)}</em></span></button>)}{!visibleApprovals.length && <p className="empty tableEmpty">No proposals match this filter.</p>}</div></div>
          </section>}

          {tab === 'audit' && <section className="pageSection">
            <div className="pageHead"><div><p className="eyebrow">Append-only evidence</p><h1>The decision trail.</h1><p>Matches, component verification, policy decisions, and human approvals are independently attributable.</p></div><div className="summaryChip"><span>Events shown</span><strong>{data.audit.length}</strong></div></div>
            <div className="auditLayout"><article className="timeline">{data.audit.map((item, index) => <div className="timelineEvent" key={`${item.event}-${item.proposal_id || item.bank_txn_id || index}-${index}`}><span className="eventDot" /><div className="eventBody"><div><strong>{eventLabel(item.event)}</strong><time>{item.at ? new Date(item.at).toLocaleString() : `Event ${data.audit.length - index}`}</time></div><p>{item.proposal_id ? `${item.proposal_id} · ${item.decision || item.status}` : item.bank_txn_id ? `${item.bank_txn_id}${item.settlement_id ? ` → ${item.settlement_id}` : ''}` : item.status || 'Deterministic controller event'}</p>{item.reviewer && <small>Reviewer: {item.reviewer}</small>}</div></div>)}{!data.audit.length && <p className="empty">Connect the local API to load the audit trail.</p>}</article><aside className="auditRules"><span className="kicker">Invariants</span><h2>What the trail proves</h2><ul><li><i>01</i><span><strong>No model arithmetic</strong>All amounts originate in deterministic code.</span></li><li><i>02</i><span><strong>Source-level citations</strong>Every exception points back to exact CSV rows.</span></li><li><i>03</i><span><strong>Idempotent posting</strong>Proposal IDs are unique ledger keys.</span></li><li><i>04</i><span><strong>Human authority</strong>Only an approval interrupt can reach the sandbox ledger.</span></li></ul></aside></div>
          </section>}
        </div>
      </section>

      {(selectedJournal || selectedRisk || selectedGraph) && <div className="scrim" onMouseDown={() => { setSelectedJournal(null); setSelectedRisk(null); setSelectedGraph(null); }}><aside className="drawer" onMouseDown={event => event.stopPropagation()}>
        <button className="closeButton" onClick={() => { setSelectedJournal(null); setSelectedRisk(null); setSelectedGraph(null); }} aria-label="Close details">×</button>
        {selectedGraph && <>
          <p className="eyebrow">{selectedGraph.certificate ? 'LedgerGraph proof certificate' : 'Rejected candidate evidence'}</p><h2>{selectedGraph.certificate?.certificate_id || shortId(selectedGraph.candidate_id)}</h2><div className={`exceptionHero graphHero ${selectedGraph.certificate ? '' : 'rejectedGraphHero'}`}><span>{selectedGraph.topology || '1:1'} topology · {evidenceLevel(selectedGraph)} · {selectedGraph.certificate ? 'globally selected as one atomic group' : eventLabel(selectedGraph.rejection_stage || 'not_selected')}</span><strong>Score {selectedGraph.evidence_score}</strong><small>{selectedGraph.bank_ids.join(' + ')} → {selectedGraph.settlement_ids.join(' + ')}</small></div>
          <div className="moneyEquation"><span>Bank total</span><strong>₹{selectedGraph.bank_total}</strong><b>−</b><span>Settlement net</span><strong>₹{selectedGraph.settlement_total}</strong><b>=</b><span>Residual</span><strong className={Number(selectedGraph.residual) === 0 ? 'safeText' : 'debitText'}>₹{selectedGraph.residual}</strong></div>
          <div className="reasonBlock"><span>Transparent score breakdown</span>{selectedGraph.features.map(feature => <div className="featureRow" key={feature.feature}><strong>+{feature.points}</strong><p><b>{eventLabel(feature.feature)}</b>{feature.detail}</p></div>)}</div>
          {selectedGraph.certificate ? <div className="citations"><span>Hard constraints satisfied</span>{selectedGraph.certificate.constraints_satisfied.map(rule => <code key={rule}>✓ {eventLabel(rule)}</code>)}</div> : <div className="citations rejectedRules"><span>Selection blockers</span>{selectedGraph.blockers.map(rule => <code key={rule}>× {eventLabel(rule)}</code>)}</div>}
          {!!selectedGraph.certificate?.rejected_alternatives.length && <div className="alternatives"><span>Nearest rejected alternatives</span>{selectedGraph.certificate.rejected_alternatives.map(item => <div key={item.candidate_id}><strong>{shortId(item.candidate_id)}</strong><small>score {item.evidence_score} · {item.reason}</small></div>)}</div>}
          <div className="gateNotice"><span>◆</span><p><strong>Authority boundary</strong>The certificate was computed by deterministic code. Qwen may explain it, but cannot change the edge, score, amount, or approval state.</p></div>
        </>}
        {selectedJournal && <>
          <p className="eyebrow">Atomic {selectedJournal.topology || '1:1'} journal proposal</p><h2>{selectedJournal.proposal_id}</h2><div className="drawerMeta"><div><span>Bank group</span><strong>{(selectedJournal.bank_txn_ids || [selectedJournal.bank_txn_id]).join(' + ')}</strong></div><div><span>Settlement group</span><strong>{(selectedJournal.settlement_ids || [selectedJournal.settlement_id]).join(' + ')}</strong></div><div><span>Total value</span><strong>{selectedJournal.display_amount}</strong></div><div><span>Balance check</span><strong className="safeText">✓ Group debit = credit</strong></div></div>
          <div className="journal"><div className="journalHead"><span>Account</span><span>Debit</span><span>Credit</span></div>{selectedJournal.entries.map(entry => <div key={entry.account}><strong>{entry.account}</strong><span>{Number(entry.debit) ? `₹${Number(entry.debit).toLocaleString('en-IN',{minimumFractionDigits:2})}` : '—'}</span><span>{Number(entry.credit) ? `₹${Number(entry.credit).toLocaleString('en-IN',{minimumFractionDigits:2})}` : '—'}</span></div>)}<div className="journalTotal"><strong>Total</strong><span>{selectedJournal.display_amount}</span><span>{selectedJournal.display_amount}</span></div></div>
          <div className="gateNotice"><span>◆</span><p><strong>LangGraph human gate</strong>{selectedJournal.approval.reason}. No financial fields can be edited here.</p></div>
          {selectedJournal.workflow_status === 'awaiting_human_approval' ? <div className="drawerActions"><button className="rejectButton" onClick={() => decide(selectedJournal, 'reject')} disabled={busy}>Reject</button><button className="approveButton" onClick={() => decide(selectedJournal, 'approve')} disabled={busy}>{busy ? 'Recording…' : 'Approve to sandbox ledger'} <span>→</span></button></div> : <div className="decisionReceipt"><span className={selectedJournal.workflow_status === 'rejected' ? 'badReceipt' : ''}>{selectedJournal.workflow_status === 'rejected' ? '×' : '✓'}</span><div><strong>{eventLabel(selectedJournal.workflow_status)}</strong><small>{selectedJournal.ledger_entry_id || selectedJournal.reviewer || 'Decision recorded'}</small></div></div>}
        </>}
        {selectedRisk && <>
          <p className="eyebrow">Dubious bank-entry evidence</p><h2>{selectedRisk.bank_txn_id}</h2><div className="exceptionHero"><span>{selectedRisk.direction} under review</span><strong>{selectedRisk.amount_display}</strong><small>{selectedRisk.risk_title}</small></div><div className="drawerMeta"><div><span>Direction</span><strong className={selectedRisk.direction === 'debit' ? 'debitText' : 'creditText'}>{selectedRisk.direction.toUpperCase()}</strong></div><div><span>Severity</span><strong>{selectedRisk.severity.toUpperCase()}</strong></div><div><span>Transaction timestamp</span><strong>{timestamp(selectedRisk.transaction_timestamp_utc)}</strong></div><div><span>Source extracted</span><strong>{timestamp(selectedRisk.source_extracted_at_utc)}</strong></div></div>{selectedRisk.scenario_context && <div className="scenarioEvidence"><div><ScenarioBadge context={selectedRisk.scenario_context} /><strong>{selectedRisk.scenario_context.label}</strong></div><p>{selectedRisk.scenario_context.realism_basis}</p><small><b>Evidence required:</b> {selectedRisk.scenario_context.required_sources.join(' · ')}</small><small><b>Claim boundary:</b> {selectedRisk.scenario_context.claim_boundary}</small></div>}<div className="reasonBlock"><span>Why it was flagged</span><h3>{selectedRisk.reason}</h3></div><div className="evidenceText"><span>Observed bank text</span><p>{selectedRisk.observed_text}</p></div><div className="evidenceText"><span>Expected independent evidence</span><p>{selectedRisk.expected_text}</p></div>
          {selectedRisk.graph_ood && <div className={`graphRiskReceipt ${selectedRisk.graph_ood.is_graph_ood ? 'graphRiskFlagged' : ''}`}><div><span>Graph nonconformity</span><strong>{selectedRisk.graph_ood.score} / 100</strong><small>review threshold {selectedRisk.graph_ood.threshold}</small></div><div className="graphRiskSignals">{selectedRisk.graph_ood.signals.map(signal => <article key={signal.code}><b>+{signal.points}</b><p><strong>{eventLabel(signal.code)}</strong><small>{signal.detail}</small></p></article>)}</div>{!!selectedRisk.graph_ood.evidence_path.length && <div className="evidencePath">{selectedRisk.graph_ood.evidence_path.map((node, index) => <span key={node}>{index > 0 && <i>→</i>}<code>{node}</code></span>)}</div>}</div>}
          <div className="gateNotice"><span>!</span><p><strong>Recommended auditor action</strong>{selectedRisk.recommended_action}</p></div><div className="citations"><span>Exact evidence rows</span>{selectedRisk.citations.map(citation => <code key={citation}>{citation}</code>)}</div><div className="detectionStamp">{selectedRisk.risk_engine || 'Deterministic controls'} · detected {timestamp(selectedRisk.detected_at_utc)}</div>
        </>}
      </aside></div>}
    </main>
  );
}
