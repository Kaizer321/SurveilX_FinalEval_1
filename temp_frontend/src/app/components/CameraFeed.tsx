import { Circle, AlertCircle, Radio } from 'lucide-react';

interface CameraFeedProps {
  id: string;
  name: string;
  location: string;
  streamUrl?: string;
  enabled: boolean;
  detectionLabel?: string;
  detectionScore?: number | null;
  isAlert?: boolean;
}

export function CameraFeed({
  id,
  name,
  location,
  streamUrl,
  enabled,
  detectionLabel,
  detectionScore,
  isAlert,
}: CameraFeedProps) {
  const scoreLabel = typeof detectionScore === 'number' ? `${Math.round(detectionScore * 100)}%` : 'n/a';

  return (
    <div className="overflow-hidden rounded-2xl border border-white/10 bg-slate-950/80 shadow-[0_24px_60px_rgba(2,6,23,0.35)] backdrop-blur">
      {/* Camera View */}
      <div className="relative aspect-video bg-slate-900">
        {enabled ? (
          streamUrl ? (
            <img src={streamUrl} alt={name} className="h-full w-full object-cover" />
          ) : (
            <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800">
              <div className="text-center text-slate-400">
                <Radio className="mx-auto mb-3 h-12 w-12 animate-pulse" />
                <p className="text-xs uppercase tracking-[0.32em] text-slate-500">Live feed pending</p>
              </div>
            </div>
          )
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-slate-950">
            <div className="text-center text-slate-400">
              <AlertCircle className="mx-auto mb-2 h-12 w-12" />
              <p className="text-sm">Camera disabled</p>
            </div>
          </div>
        )}

        {/* Status Indicators Overlay */}
        <div className="absolute left-3 top-3 flex flex-wrap gap-2">
          <div className="flex items-center gap-1.5 rounded-full border border-white/10 bg-black/70 px-2.5 py-1 text-[11px] uppercase tracking-[0.24em] text-white/90 backdrop-blur">
            <Circle className="h-2 w-2 fill-emerald-400 text-emerald-400" />
            <span>Live</span>
          </div>
          {isAlert && (
            <div className="flex items-center gap-1.5 rounded-full border border-rose-500/40 bg-rose-500/90 px-2.5 py-1 text-[11px] uppercase tracking-[0.24em] text-white backdrop-blur">
              <Circle className="h-2 w-2 fill-white animate-pulse" />
              <span>Alert</span>
            </div>
          )}
          {detectionLabel && (
            <div className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/10 px-2.5 py-1 text-[11px] uppercase tracking-[0.24em] text-white backdrop-blur">
              <span>{detectionLabel}</span>
            </div>
          )}
        </div>

        <div className="absolute bottom-3 right-3 rounded-full border border-white/10 bg-black/70 px-3 py-1.5 text-[11px] font-medium uppercase tracking-[0.22em] text-white/80 backdrop-blur">
          <span>{scoreLabel}</span>
        </div>
      </div>

      {/* Camera Info */}
      <div className="border-t border-white/10 p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-white">{name}</h3>
            <p className="mt-1 text-xs text-slate-400">{location}</p>
          </div>
          <div className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1">
            <Circle
              className={`h-2 w-2 ${
                enabled ? 'fill-emerald-500 text-emerald-500' : 'fill-rose-500 text-rose-500'
              }`}
            />
            <span className="text-xs text-slate-300">
              {enabled ? 'Online' : 'Offline'}
            </span>
          </div>
        </div>
        <div className="mt-3 flex items-center justify-between text-xs text-slate-400">
          <span>ID {id}</span>
          <span>{enabled ? 'Streaming from backend' : 'Awaiting camera source'}</span>
        </div>
      </div>
    </div>
  );
}
