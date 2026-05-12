import { Bell, AlertTriangle, Info, CheckCircle, X } from 'lucide-react';

interface Alert {
  id: string;
  type: 'warning' | 'info' | 'success';
  title: string;
  message: string;
  camera: string;
  time: string;
  score?: string;
}

interface AlertPanelProps {
  alerts: Alert[];
  onDismiss: (id: string) => void;
}

export function AlertPanel({ alerts, onDismiss }: AlertPanelProps) {
  const getAlertIcon = (type: string) => {
    switch (type) {
      case 'warning':
        return <AlertTriangle className="w-5 h-5 text-yellow-500" />;
      case 'info':
        return <Info className="w-5 h-5 text-blue-500" />;
      case 'success':
        return <CheckCircle className="w-5 h-5 text-green-500" />;
      default:
        return <Bell className="w-5 h-5" />;
    }
  };

  return (
    <div className="space-y-3">
      {alerts.length === 0 ? (
        <div className="rounded-2xl border border-white/10 bg-slate-950/80 p-5 text-sm text-slate-400 shadow-[0_24px_60px_rgba(2,6,23,0.35)]">
          No active detections right now. The dashboard will populate here when the backend flags an event.
        </div>
      ) : (
        alerts.map((alert) => (
          <div
            key={alert.id}
            className="rounded-2xl border border-white/10 bg-slate-950/80 p-4 shadow-[0_24px_60px_rgba(2,6,23,0.35)] backdrop-blur"
          >
            <div className="flex items-start gap-3">
              <div className="mt-0.5">{getAlertIcon(alert.type)}</div>
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-2">
                  <h4 className="text-sm font-medium text-white">{alert.title}</h4>
                  <button
                    onClick={() => onDismiss(alert.id)}
                    className="rounded-full p-1 text-slate-400 transition-colors hover:bg-white/5 hover:text-white"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
                <p className="mt-1 text-xs leading-5 text-slate-400">{alert.message}</p>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.22em] text-slate-500">
                  <span>{alert.camera}</span>
                  <span>•</span>
                  <span>{alert.time}</span>
                  {alert.score && (
                    <>
                      <span>•</span>
                      <span>{alert.score}</span>
                    </>
                  )}
                </div>
              </div>
            </div>
          </div>
        ))
      )}
    </div>
  );
}
