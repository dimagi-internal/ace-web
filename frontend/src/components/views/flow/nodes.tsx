import { Handle, Position, type NodeProps } from "@xyflow/react";
import { CheckCircle2, FileText, MessageSquare, Scale, ShieldCheck, XCircle } from "lucide-react";

const HANDLE_STYLE = { width: 6, height: 6, background: "#475569" };

interface BaseNodeData {
  label: string;
  sub?: string;
  href?: string;
  /** Used by VerdictNode only. */
  passed?: boolean | null;
  [key: string]: unknown;
}

function NodeShell({
  border,
  bgFrom,
  ico,
  iconColor,
  data,
}: {
  border: string;
  bgFrom: string;
  ico: React.ReactNode;
  iconColor: string;
  data: BaseNodeData;
}) {
  const body = (
    <div
      className={`flex w-[220px] items-start gap-2 rounded-md border ${border} px-3 py-2 text-xs shadow-md`}
      style={{
        background: `linear-gradient(180deg, ${bgFrom} 0%, hsl(var(--card)) 100%)`,
      }}
    >
      <span className={`mt-0.5 shrink-0 ${iconColor}`}>{ico}</span>
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium text-foreground" title={data.label}>
          {data.label}
        </div>
        {data.sub && (
          <div className="truncate text-[10px] text-muted-foreground" title={data.sub}>
            {data.sub}
          </div>
        )}
      </div>
    </div>
  );
  if (data.href) {
    return (
      <a
        href={data.href}
        className="block no-underline"
        onClick={(e) => e.stopPropagation()}
      >
        {body}
      </a>
    );
  }
  return body;
}

export function ChatNode({ data }: NodeProps) {
  return (
    <>
      <Handle type="target" position={Position.Left} style={HANDLE_STYLE} />
      <NodeShell
        border="border-indigo-500/60"
        bgFrom="rgba(99,102,241,0.12)"
        iconColor="text-indigo-400"
        ico={<MessageSquare className="h-3.5 w-3.5" />}
        data={data as BaseNodeData}
      />
      <Handle type="source" position={Position.Right} style={HANDLE_STYLE} />
    </>
  );
}

export function ArtifactNode({ data }: NodeProps) {
  return (
    <>
      <Handle type="target" position={Position.Left} style={HANDLE_STYLE} />
      <NodeShell
        border="border-purple-500/60"
        bgFrom="rgba(168,85,247,0.12)"
        iconColor="text-purple-400"
        ico={<FileText className="h-3.5 w-3.5" />}
        data={data as BaseNodeData}
      />
      <Handle type="source" position={Position.Right} style={HANDLE_STYLE} />
    </>
  );
}

export function VerdictNode({ data }: NodeProps) {
  const d = data as BaseNodeData;
  const isFail = d.passed === false;
  return (
    <>
      <Handle type="target" position={Position.Left} style={HANDLE_STYLE} />
      <NodeShell
        border={isFail ? "border-red-500/60" : "border-emerald-500/60"}
        bgFrom={isFail ? "rgba(239,68,68,0.12)" : "rgba(34,197,94,0.12)"}
        iconColor={isFail ? "text-red-400" : "text-emerald-400"}
        ico={
          isFail ? (
            <XCircle className="h-3.5 w-3.5" />
          ) : d.passed === true ? (
            <CheckCircle2 className="h-3.5 w-3.5" />
          ) : (
            <Scale className="h-3.5 w-3.5" />
          )
        }
        data={d}
      />
      <Handle type="source" position={Position.Right} style={HANDLE_STYLE} />
    </>
  );
}

export function GateNode({ data }: NodeProps) {
  return (
    <>
      <Handle type="target" position={Position.Left} style={HANDLE_STYLE} />
      <NodeShell
        border="border-amber-500/60"
        bgFrom="rgba(245,158,11,0.12)"
        iconColor="text-amber-400"
        ico={<ShieldCheck className="h-3.5 w-3.5" />}
        data={data as BaseNodeData}
      />
      <Handle type="source" position={Position.Right} style={HANDLE_STYLE} />
    </>
  );
}

export const NODE_TYPES = {
  chat: ChatNode,
  artifact: ArtifactNode,
  verdict: VerdictNode,
  gate: GateNode,
};
