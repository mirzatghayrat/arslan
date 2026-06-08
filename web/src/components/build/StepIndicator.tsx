const NODES = ["domain", "capabilities", "persona", "runtime", "spawn_name"];

export default function StepIndicator({ activeNode }: { activeNode: string }) {
  const activeIndex = NODES.indexOf(activeNode);
  return (
    <div className="mb-6 flex gap-2">
      {NODES.map((node, i) => (
        <div
          key={node}
          className={`h-1.5 flex-1 rounded-full ${
            i <= activeIndex ? "bg-amber" : "bg-white/15"
          }`}
        />
      ))}
    </div>
  );
}
