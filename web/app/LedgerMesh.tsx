'use client';

import { PointerEvent as ReactPointerEvent, useEffect, useMemo, useRef, useState } from 'react';

export type RawNode = {
  id: string; amount?: string; date_candidates?: string[]; narration?: string;
  utr?: string; component_count?: number;
  capture_date?: string; settlement_cycle?: string; settled_at?: string;
  working_day_path?: string; chronology_valid?: boolean;
};

export type MeshEdge = {
  candidate_id: string; bank_ids: string[]; settlement_ids: string[];
  evidence_score: number; residual: string; eligible: boolean; selected?: boolean;
  blockers: string[]; topology?: string; kind?: string;
  rejection_stage?: string;
};

export type MeshData = { bank_nodes: RawNode[]; settlement_nodes: RawNode[]; edges: MeshEdge[] };
type NodeView = RawNode & { key: string; type: 'bank' | 'settlement'; x: number; y: number; degree: number };
type Viewport = { scale: number; x: number; y: number };
type Topology = 'all' | '1:1' | '1:N' | 'N:1' | 'N:M';
type FactorView = { edge: MeshEdge; x: number; y: number };
type SegmentView = { edge: MeshEdge; ax: number; ay: number; bx: number; by: number };

const TOPOLOGIES: Topology[] = ['all', '1:1', '1:N', 'N:1', 'N:M'];

function edgeTopology(edge: MeshEdge): Exclude<Topology, 'all'> {
  if (edge.topology) return edge.topology as Exclude<Topology, 'all'>;
  if (edge.bank_ids.length === 1 && edge.settlement_ids.length === 1) return '1:1';
  if (edge.bank_ids.length === 1) return '1:N';
  if (edge.settlement_ids.length === 1) return 'N:1';
  return 'N:M';
}

function hash(value: string): number {
  let result = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    result ^= value.charCodeAt(index);
    result = Math.imul(result, 16777619);
  }
  return result >>> 0;
}

function pointSegmentDistance(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax; const dy = by - ay;
  if (!dx && !dy) return Math.hypot(px - ax, py - ay);
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

export default function LedgerMesh({ mesh, mode, onSelectEdge }: {
  mesh: MeshData; mode: 'candidates' | 'solution'; onSelectEdge: (edge: unknown) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ x: number; y: number; viewX: number; viewY: number; moved: boolean } | null>(null);
  const [size, setSize] = useState({ width: 900, height: 620 });
  const [view, setView] = useState<Viewport>({ scale: 1, x: 0, y: 0 });
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [hoveredEdge, setHoveredEdge] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [topologyFilter, setTopologyFilter] = useState<Topology>('all');

  const modeEdges = useMemo(
    () => (mesh?.edges || []).filter(edge => mode === 'candidates' || edge.selected),
    [mesh, mode],
  );
  const topologyCounts = useMemo(() => Object.fromEntries(
    TOPOLOGIES.map(topology => [
      topology,
      topology === 'all' ? modeEdges.length : modeEdges.filter(edge => edgeTopology(edge) === topology).length,
    ]),
  ) as Record<Topology, number>, [modeEdges]);
  const topologyDecisionCounts = useMemo(() => Object.fromEntries(
    TOPOLOGIES.map(topology => {
      const edges = modeEdges.filter(edge => topology === 'all' || edgeTopology(edge) === topology);
      return [topology, {
        selected: edges.filter(edge => edge.selected).length,
        hard: edges.filter(edge => edge.rejection_stage === 'hard_gate_rejected' || edge.rejection_stage === 'threshold_rejected').length,
        global: edges.filter(edge => edge.rejection_stage === 'global_solver_rejected').length,
      }];
    }),
  ) as Record<Topology, { selected: number; hard: number; global: number }>, [modeEdges]);
  const displayedEdges = useMemo(
    () => modeEdges.filter(edge => topologyFilter === 'all' || edgeTopology(edge) === topologyFilter),
    [modeEdges, topologyFilter],
  );

  const degree = useMemo(() => {
    const counts = new Map<string, number>();
    displayedEdges.forEach(edge => {
      edge.bank_ids.forEach(id => counts.set(`B:${id}`, (counts.get(`B:${id}`) || 0) + 1));
      edge.settlement_ids.forEach(id => counts.set(`S:${id}`, (counts.get(`S:${id}`) || 0) + 1));
    });
    return counts;
  }, [displayedEdges]);

  const nodes = useMemo(() => {
    const usableHeight = Math.max(300, size.height - 80);
    const build = (node: RawNode, type: 'bank' | 'settlement'): NodeView => {
      const seed = hash(`${type}:${node.id}`);
      const xBand = type === 'bank' ? [0.10, 0.46] : [0.54, 0.90];
      const x = size.width * (xBand[0] + ((seed % 1000) / 1000) * (xBand[1] - xBand[0]));
      const y = 40 + ((hash(`${node.id}:y`) % 10000) / 10000) * usableHeight;
      const key = `${type === 'bank' ? 'B' : 'S'}:${node.id}`;
      return { ...node, key, type, x, y, degree: degree.get(key) || 0 };
    };
    return [
      ...(mesh?.bank_nodes || []).map(node => build(node, 'bank')),
      ...(mesh?.settlement_nodes || []).map(node => build(node, 'settlement')),
    ];
  }, [mesh, size, degree]);

  const nodeByKey = useMemo(() => new Map(nodes.map(node => [node.key, node])), [nodes]);
  const factors = useMemo(() => displayedEdges.flatMap((edge): FactorView[] => {
    if (edgeTopology(edge) === '1:1') return [];
    const members = [
      ...edge.bank_ids.map(id => nodeByKey.get(`B:${id}`)),
      ...edge.settlement_ids.map(id => nodeByKey.get(`S:${id}`)),
    ].filter(Boolean) as NodeView[];
    if (!members.length) return [];
    const jitter = ((hash(edge.candidate_id) % 21) - 10) * .8;
    return [{
      edge,
      x: members.reduce((total, node) => total + node.x, 0) / members.length,
      y: members.reduce((total, node) => total + node.y, 0) / members.length + jitter,
    }];
  }), [displayedEdges, nodeByKey]);
  const factorByCandidate = useMemo(
    () => new Map(factors.map(factor => [factor.edge.candidate_id, factor])),
    [factors],
  );
  const segments = useMemo(() => displayedEdges.flatMap((edge): SegmentView[] => {
    const banks = edge.bank_ids.map(id => nodeByKey.get(`B:${id}`)).filter(Boolean) as NodeView[];
    const settlements = edge.settlement_ids.map(id => nodeByKey.get(`S:${id}`)).filter(Boolean) as NodeView[];
    const factor = factorByCandidate.get(edge.candidate_id);
    if (factor) return [
      ...banks.map(node => ({ edge, ax: node.x, ay: node.y, bx: factor.x, by: factor.y })),
      ...settlements.map(node => ({ edge, ax: factor.x, ay: factor.y, bx: node.x, by: node.y })),
    ];
    if (!banks[0] || !settlements[0]) return [];
    return [{ edge, ax: banks[0].x, ay: banks[0].y, bx: settlements[0].x, by: settlements[0].y }];
  }), [displayedEdges, nodeByKey, factorByCandidate]);
  const selected = selectedNode ? nodeByKey.get(selectedNode) || null : null;
  const connectedEdges = selected
    ? displayedEdges.filter(edge => selected.type === 'bank' ? edge.bank_ids.includes(selected.id) : edge.settlement_ids.includes(selected.id))
    : [];

  useEffect(() => {
    const element = wrapRef.current;
    if (!element) return;
    const update = () => setSize({
      width: Math.max(280, element.clientWidth),
      height: Math.max(380, Math.min(680, window.innerHeight * 0.66)),
    });
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const handleWheel = (event: globalThis.WheelEvent) => {
      event.preventDefault();
      event.stopPropagation();
      const rect = canvas.getBoundingClientRect();
      const pointerX = event.clientX - rect.left;
      const pointerY = event.clientY - rect.top;
      setView(current => {
        const nextScale = Math.max(.55, Math.min(2.4, current.scale * (event.deltaY > 0 ? .9 : 1.1)));
        const worldX = (pointerX - current.x) / current.scale;
        const worldY = (pointerY - current.y) / current.scale;
        return { scale: nextScale, x: pointerX - worldX * nextScale, y: pointerY - worldY * nextScale };
      });
    };

    canvas.addEventListener('wheel', handleWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', handleWheel);
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(size.width * ratio);
    canvas.height = Math.round(size.height * ratio);
    canvas.style.width = `${size.width}px`;
    canvas.style.height = `${size.height}px`;
    const context = canvas.getContext('2d');
    if (!context) return;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, size.width, size.height);
    context.save();
    context.translate(view.x, view.y);
    context.scale(view.scale, view.scale);

    const focusKey = selectedNode || hoveredNode;
    segments.forEach(segment => {
        const { edge } = segment;
        const touchesFocus = !focusKey
          || edge.bank_ids.some(id => `B:${id}` === focusKey)
          || edge.settlement_ids.some(id => `S:${id}` === focusKey);
        const isHovered = hoveredEdge === edge.candidate_id;
        context.beginPath();
        context.moveTo(segment.ax, segment.ay);
        context.lineTo(segment.bx, segment.by);
        context.setLineDash(edge.selected ? [] : [4, 5]);
        context.lineWidth = isHovered ? 3 : edge.selected ? 1.25 : 0.85;
        context.strokeStyle = edge.selected
          ? `rgba(83, 205, 143, ${touchesFocus ? (isHovered ? 1 : .55) : .06})`
          : `rgba(203, 105, 79, ${touchesFocus ? (isHovered ? .95 : .28) : .035})`;
        context.stroke();
    });
    context.setLineDash([]);

    factors.forEach(factor => {
      const isHovered = hoveredEdge === factor.edge.candidate_id;
      const radius = isHovered ? 7 : 5;
      context.beginPath();
      context.arc(factor.x, factor.y, radius, 0, Math.PI * 2);
      context.fillStyle = factor.edge.selected ? '#7de4aa' : '#bd6d59';
      context.fill();
      context.lineWidth = 2;
      context.strokeStyle = '#06100c';
      context.stroke();
      if (isHovered) {
        context.font = `${12 / view.scale}px ui-monospace, monospace`;
        context.fillStyle = '#e1ece7';
        context.fillText(edgeTopology(factor.edge), factor.x + 10, factor.y - 8);
      }
    });

    nodes.forEach(node => {
      const focused = !focusKey || node.key === focusKey || displayedEdges.some(edge => {
        if (focusKey?.startsWith('B:')) return edge.bank_ids.includes(focusKey.slice(2)) && edge.settlement_ids.includes(node.id);
        if (focusKey?.startsWith('S:')) return edge.settlement_ids.includes(focusKey.slice(2)) && edge.bank_ids.includes(node.id);
        return false;
      });
      const hovered = node.key === hoveredNode;
      const chosen = node.key === selectedNode;
      const radius = (node.degree > 1 ? 5.5 : 3.7) + (hovered || chosen ? 3 : 0);
      context.beginPath(); context.arc(node.x, node.y, radius, 0, Math.PI * 2);
      context.fillStyle = node.type === 'bank'
        ? `rgba(94, 180, 222, ${focused ? .95 : .16})`
        : `rgba(208, 168, 86, ${focused ? .95 : .16})`;
      context.fill();
      context.lineWidth = chosen ? 2.5 : node.degree > 1 ? 1.5 : .7;
      context.strokeStyle = chosen ? '#f0f8f4' : node.degree > 1 ? '#b8d6c8' : '#203f34';
      context.stroke();
      if (hovered || chosen) {
        context.font = `${13 / view.scale}px ui-monospace, monospace`;
        context.fillStyle = '#e1ece7';
        context.fillText(node.id, node.x + radius + 5, node.y - radius - 2);
      }
    });
    context.restore();
  }, [size, view, nodes, displayedEdges, segments, factors, hoveredNode, hoveredEdge, selectedNode]);

  const pointerWorld = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: (event.clientX - rect.left - view.x) / view.scale, y: (event.clientY - rect.top - view.y) / view.scale };
  };

  const hitTest = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const point = pointerWorld(event);
    const node = [...nodes].reverse().find(item => Math.hypot(point.x - item.x, point.y - item.y) <= 10 / view.scale);
    if (node) return { node, edge: null as MeshEdge | null };
    const factor = [...factors].reverse().find(item => Math.hypot(point.x - item.x, point.y - item.y) <= 10 / view.scale);
    if (factor) return { node: null as NodeView | null, edge: factor.edge };
    const edge = [...segments].reverse().find(item => (
      pointSegmentDistance(point.x, point.y, item.ax, item.ay, item.bx, item.by) <= 5 / view.scale
    ))?.edge;
    return { node: null as NodeView | null, edge: edge || null };
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const drag = dragRef.current;
    if (drag) {
      const dx = event.clientX - drag.x; const dy = event.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
      setView(current => ({ ...current, x: drag.viewX + dx, y: drag.viewY + dy }));
      return;
    }
    const hit = hitTest(event);
    setHoveredNode(hit.node?.key || null); setHoveredEdge(hit.edge?.candidate_id || null);
    event.currentTarget.style.cursor = hit.node || hit.edge ? 'pointer' : 'grab';
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    dragRef.current = { x: event.clientX, y: event.clientY, viewX: view.x, viewY: view.y, moved: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerUp = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const drag = dragRef.current; dragRef.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
    if (drag?.moved) return;
    const hit = hitTest(event);
    if (hit.node) setSelectedNode(hit.node.key);
    else if (hit.edge) onSelectEdge(hit.edge);
    else setSelectedNode(null);
  };

  const zoom = (factor: number) => setView(current => ({ ...current, scale: Math.max(.55, Math.min(2.4, current.scale * factor)) }));
  const reset = () => { setView({ scale: 1, x: 0, y: 0 }); setSelectedNode(null); };

  return <>
    <div className="topologyRail" role="group" aria-label="Filter reconciliation topology">
      {TOPOLOGIES.map(topology => <button key={topology} className={topologyFilter === topology ? 'active' : ''} onClick={() => setTopologyFilter(topology)}><span>{topology === 'all' ? 'ALL' : topology}</span><strong>{topologyCounts[topology]}</strong><small>{mode === 'candidates' ? `${topologyDecisionCounts[topology].hard} hard · ${topologyDecisionCounts[topology].global} global · ${topologyDecisionCounts[topology].selected} selected` : topology === 'all' ? 'selected groups' : topology === '1:1' ? 'direct' : topology === '1:N' ? 'aggregated' : topology === 'N:1' ? 'split' : 'netted group'}</small></button>)}
    </div>
    <div className="meshWorkspace">
    <div className="meshViewport" ref={wrapRef}>
      <canvas ref={canvasRef} width={size.width} height={size.height} tabIndex={0} role="img" aria-label={`Interactive reconciliation graph with ${nodes.length} money nodes, ${factors.length} atomic group nodes, and ${displayedEdges.length} hypotheses. Drag to pan, use the mouse wheel to zoom, and click a node or edge for evidence.`} onPointerMove={onPointerMove} onPointerLeave={() => { setHoveredNode(null); setHoveredEdge(null); dragRef.current = null; }} onPointerDown={onPointerDown} onPointerUp={onPointerUp} />
      <div className="meshHud"><span>{nodes.length} money nodes</span><span>{factors.length} group nodes</span><span>{displayedEdges.length} hypotheses</span><span>{mode === 'candidates' ? 'unsolved mesh' : 'selected solution'}</span></div>
      <div className="meshControls"><button onClick={() => zoom(1.18)} aria-label="Zoom in">+</button><button onClick={() => zoom(.85)} aria-label="Zoom out">−</button><button onClick={reset}>Reset</button></div>
      <div className="meshHint">Small centre circles are atomic group hypotheses · drag · wheel · click</div>
    </div>
    <aside className="meshInspector">
      {selected ? <>
        <div className={`inspectorNodeMark ${selected.type}`}><i /></div>
        <span>{selected.type === 'bank' ? 'Simulated bank node' : 'Razorpay settlement node'}</span>
        <h3>{selected.id}</h3>
        <strong>₹{Number(selected.amount || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}</strong>
        <div className="inspectorFacts"><div><span>Candidate degree</span><b>{selected.degree}</b></div><div><span>Node state</span><b>{selected.degree > 1 ? 'CONTESTED' : 'SINGLE PATH'}</b></div></div>
        {(selected.narration || selected.utr) && <p>{selected.narration || `UTR ${selected.utr}`}</p>}
        {!!selected.date_candidates?.length && <small>Dates: {selected.date_candidates.join(' · ')}</small>}
        {selected.type === 'settlement' && selected.capture_date && <div className="chronologyCard"><span>Timing proof</span><div><b>{selected.capture_date}</b><i>{selected.settlement_cycle || 'cycle'}</i><b>{selected.settled_at || '—'}</b></div><p>{selected.working_day_path}</p><small>{selected.chronology_valid ? '✓ Calendar invariant passed' : '! Calendar invariant failed'}</small></div>}
        <div className="connectedEdgeList"><span>Connected hypotheses</span>{connectedEdges.map(edge => <button key={edge.candidate_id} onClick={() => onSelectEdge(edge)}><i className={edge.selected ? 'edgeSelectedDot' : 'edgeRejectedDot'} /><div><strong>{edge.selected ? 'Selected' : 'Rejected'} · score {edge.evidence_score}</strong><small>{edge.bank_ids.join(' + ')} → {edge.settlement_ids.join(' + ')}</small></div></button>)}</div>
      </> : <div className="inspectorEmpty"><i /><span>Nothing selected</span><h3>Click any circle.</h3><p>Node identity, amount, degree, dates, narration and every connected hypothesis will appear here.</p><small>Blue circles are bank entries. Gold circles are Razorpay settlements.</small></div>}
    </aside>
    </div>
  </>;
}
