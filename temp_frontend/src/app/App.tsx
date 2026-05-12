import { useEffect, useMemo, useState, type FormEvent } from 'react';
import {
  Activity,
  AlertTriangle,
  Camera,
  CircleAlert,
  Cpu,
  Eye,
  HardDrive,
  LogOut,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  User,
} from 'lucide-react';
import { CameraFeed } from './components/CameraFeed';
import { AlertPanel } from './components/AlertPanel';
import { Sidebar } from './components/Sidebar';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from './components/ui/dialog';
import apiClient from '../utils/api';
import { useAuthStore } from '../utils/authStore';

type DashboardCamera = {
  id: string;
  name: string;
  location: string;
  enabled: boolean;
  streamUrl: string;
};

type DashboardAlert = {
  id: string;
  type: 'warning' | 'info' | 'success';
  title: string;
  message: string;
  camera: string;
  time: string;
  score?: string;
};

type DetectionRecord = {
  label?: string;
  score?: number;
  ts?: string;
  is_alert?: boolean;
  class_probs?: Record<string, number>;
};

function formatRelativeTime(value?: string) {
  if (!value) return 'just now';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const deltaSeconds = Math.max(1, Math.floor((Date.now() - parsed.getTime()) / 1000));
  if (deltaSeconds < 60) return `${deltaSeconds}s ago`;
  const deltaMinutes = Math.floor(deltaSeconds / 60);
  if (deltaMinutes < 60) return `${deltaMinutes}m ago`;
  const deltaHours = Math.floor(deltaMinutes / 60);
  if (deltaHours < 24) return `${deltaHours}h ago`;
  return `${Math.floor(deltaHours / 24)}d ago`;
}

function metricValue(value: unknown, fallback = 'n/a') {
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toString() : value.toFixed(1);
  }
  if (typeof value === 'string' && value.trim()) {
    return value;
  }
  return fallback;
}

function extractPercent(source: Record<string, unknown> | null, key: string) {
  const value = source?.[key];
  if (typeof value === 'number') {
    return metricValue(value, 'n/a');
  }
  if (value && typeof value === 'object' && 'percent' in value) {
    return metricValue((value as { percent?: unknown }).percent, 'n/a');
  }
  return metricValue(value, 'n/a');
}

export default function App() {
  const { isAuthenticated, role, login, logout, checkAuth, isLoading: authLoading, error: authError } = useAuthStore();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loginRole, setLoginRole] = useState<'user' | 'admin'>('user');
  const [activeTab, setActiveTab] = useState('grid');
  const [cameras, setCameras] = useState<DashboardCamera[]>([]);
  const [detections, setDetections] = useState<Record<string, DetectionRecord>>({});
  const [alerts, setAlerts] = useState<DashboardAlert[]>([]);
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [lastUpdated, setLastUpdated] = useState('');
  const [loadingData, setLoadingData] = useState(false);
  const [dataError, setDataError] = useState<string | null>(null);
  const [cameraDialogOpen, setCameraDialogOpen] = useState(false);
  const [creatingCamera, setCreatingCamera] = useState(false);
  const [cameraForm, setCameraForm] = useState({
    name: '',
    source_url: '',
    zone: '',
    enabled: true,
    embed_fps: '15',
  });
  const [settings, setSettings] = useState<Array<{ key: string; value: string; description?: string }>>([]);
  const [settingsEditing, setSettingsEditing] = useState<Record<string, string>>({});
  const [settingsSaving, setSettingsSaving] = useState(false);

  useEffect(() => {
    void checkAuth();
  }, [checkAuth]);

  const cameraMap = useMemo(() => new Map(cameras.map((camera) => [camera.id, camera])), [cameras]);

  const refreshData = async () => {
    setLoadingData(true);
    setDataError(null);

    try {
      const [publicCamerasResult, adminCamerasResult, detectionsResult, summaryResult, healthResult, settingsResult] = await Promise.allSettled([
        apiClient.getCameras(),
        apiClient.getAdminCameras(),
        apiClient.getLiveDetections(),
        apiClient.getAnalyticsSummary(),
        apiClient.getHealthStats(),
        apiClient.getSettings(),
      ]);

      const rawCameras = adminCamerasResult.status === 'fulfilled' && adminCamerasResult.value.length > 0
        ? adminCamerasResult.value
        : publicCamerasResult.status === 'fulfilled'
          ? publicCamerasResult.value
          : [];

      const normalizedCameras: DashboardCamera[] = rawCameras.map((camera: any) => ({
        id: String(camera.id),
        name: camera.name || `Camera ${camera.id}`,
        location: camera.zone || camera.location || 'Unassigned zone',
        enabled: typeof camera.enabled === 'boolean' ? camera.enabled : true,
        streamUrl: `/stream/${camera.id}`,
      }));

      const liveDetections = detectionsResult.status === 'fulfilled' ? detectionsResult.value : {};
      const normalizedDetections: Record<string, DetectionRecord> = liveDetections;

      const derivedAlerts = Object.entries(normalizedDetections)
        .map(([cameraId, detection]) => {
          const camera = cameraMap.get(cameraId) || normalizedCameras.find((entry) => entry.id === cameraId);
          const label = String(detection?.label || 'normal');
          const score = typeof detection?.score === 'number' ? detection.score : undefined;
          const isAlert = Boolean(detection?.is_alert);

          return {
            id: `${cameraId}-${detection?.ts || Date.now()}`,
            type: isAlert ? 'warning' : 'info',
            title: isAlert ? 'Active detection' : 'Monitoring update',
            message: isAlert
              ? `${camera?.name || `Camera ${cameraId}`} flagged ${label}.`
              : `${camera?.name || `Camera ${cameraId}`} is reporting normal activity.`,
            camera: camera?.name || `Camera ${cameraId}`,
            time: formatRelativeTime(detection?.ts),
            score: typeof score === 'number' ? `${Math.round(score * 100)}% confidence` : undefined,
          } satisfies DashboardAlert;
        })
        .sort((left, right) => (left.type === right.type ? 0 : left.type === 'warning' ? -1 : 1));

      setCameras(normalizedCameras);
      setDetections(normalizedDetections);
      setAlerts(derivedAlerts);
      setSummary(summaryResult.status === 'fulfilled' ? summaryResult.value : null);
      setHealth(healthResult.status === 'fulfilled' ? healthResult.value : null);
      
      // Load settings from backend
      if (settingsResult.status === 'fulfilled' && settingsResult.value?.settings) {
        setSettings(settingsResult.value.settings);
        // Initialize editing state with current values
        const editingState: Record<string, string> = {};
        settingsResult.value.settings.forEach((s: any) => {
          editingState[s.key] = s.value;
        });
        setSettingsEditing(editingState);
      }
      
      setLastUpdated(new Date().toLocaleTimeString());
    } catch (error) {
      setDataError(error instanceof Error ? error.message : 'Failed to load dashboard data');
    } finally {
      setLoadingData(false);
    }
  };

  useEffect(() => {
    if (!isAuthenticated) {
      setCameras([]);
      setDetections({});
      setAlerts([]);
      setSummary(null);
      setHealth(null);
      setLastUpdated('');
      setActiveTab('grid');
      return;
    }

    void refreshData();
    const timer = window.setInterval(() => {
      void refreshData();
    }, 10000);

    return () => window.clearInterval(timer);
  }, [isAuthenticated]);

  const handleLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await login(username, password, loginRole);
    await refreshData();
  };

  const handleCreateCamera = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCreatingCamera(true);
    setDataError(null);

    try {
      await apiClient.createCamera({
        name: cameraForm.name.trim(),
        source_url: cameraForm.source_url.trim(),
        zone: cameraForm.zone.trim() || undefined,
        enabled: cameraForm.enabled,
        embed_fps: Number(cameraForm.embed_fps) || undefined,
      });
      setCameraDialogOpen(false);
      setCameraForm({
        name: '',
        source_url: '',
        zone: '',
        enabled: true,
        embed_fps: '15',
      });
      await refreshData();
    } catch (error) {
      setDataError(error instanceof Error ? error.message : 'Failed to create camera');
    } finally {
      setCreatingCamera(false);
    }
  };

  const handleSaveSettings = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSettingsSaving(true);

    try {
      await apiClient.updateSettings(settingsEditing);
      // Refresh settings to confirm changes
      const result = await apiClient.getSettings();
      if (result?.settings) {
        setSettings(result.settings);
      }
      // Show success indication (you could add a toast here)
      setDataError(null);
    } catch (error) {
      setDataError(error instanceof Error ? error.message : 'Failed to save settings');
    } finally {
      setSettingsSaving(false);
    }
  };

  const onlineCameras = cameras.filter((camera) => camera.enabled).length;
  const alertCount = alerts.filter((alert) => alert.type === 'warning').length;
  const cpuValue = extractPercent(health, 'cpu');
  const ramValue = extractPercent(health, 'ram');
  const diskValue = extractPercent(health, 'disk');
  const storageValue = metricValue(summary?.storage_usage, 'n/a');

  const renderTabContent = () => {
    if (activeTab === 'cameras') {
      return (
        <section className="mt-6 space-y-5">
          <div className="rounded-[28px] border border-white/10 bg-slate-950/70 p-6 shadow-[0_24px_60px_rgba(2,6,23,0.35)]">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Camera registry</p>
                <h3 className="mt-1 text-2xl font-semibold">Configured live feeds</h3>
              </div>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                <div className="grid grid-cols-2 gap-3 text-sm text-slate-300 md:w-[360px]">
                  <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                    <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Total</p>
                    <p className="mt-2 text-xl font-semibold text-white">{cameras.length}</p>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                    <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Online</p>
                    <p className="mt-2 text-xl font-semibold text-white">{onlineCameras}</p>
                  </div>
                </div>

                <Dialog open={cameraDialogOpen} onOpenChange={setCameraDialogOpen}>
                  <DialogTrigger asChild>
                    <button
                      type="button"
                      className="inline-flex items-center justify-center rounded-2xl bg-sky-500 px-4 py-3 text-sm font-semibold text-slate-950 transition hover:bg-sky-400"
                    >
                      Add Camera
                    </button>
                  </DialogTrigger>

                  <DialogContent className="border border-white/10 bg-slate-950 text-white shadow-[0_30px_120px_rgba(2,6,23,0.75)] sm:max-w-2xl">
                    <DialogHeader className="text-left">
                      <DialogTitle className="text-2xl font-semibold">Add camera</DialogTitle>
                      <DialogDescription className="text-sm text-slate-400">
                        Create a live feed entry that matches the SURVEILX dashboard styling and backend schema.
                      </DialogDescription>
                    </DialogHeader>

                    <form onSubmit={handleCreateCamera} className="space-y-4">
                      <div className="grid gap-4 md:grid-cols-2">
                        <label className="block space-y-2 text-sm text-slate-300 md:col-span-2">
                          <span>Camera name</span>
                          <input
                            value={cameraForm.name}
                            onChange={(event) => setCameraForm((current) => ({ ...current, name: event.target.value }))}
                            className="w-full rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-white outline-none transition placeholder:text-slate-500 focus:border-sky-400"
                            placeholder="Front Gate"
                            required
                          />
                        </label>

                        <label className="block space-y-2 text-sm text-slate-300 md:col-span-2">
                          <span>Source URL</span>
                          <input
                            value={cameraForm.source_url}
                            onChange={(event) => setCameraForm((current) => ({ ...current, source_url: event.target.value }))}
                            className="w-full rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-white outline-none transition placeholder:text-slate-500 focus:border-sky-400"
                            placeholder="rtsp://... or http://..."
                            required
                          />
                        </label>

                        <label className="block space-y-2 text-sm text-slate-300">
                          <span>Zone</span>
                          <input
                            value={cameraForm.zone}
                            onChange={(event) => setCameraForm((current) => ({ ...current, zone: event.target.value }))}
                            className="w-full rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-white outline-none transition placeholder:text-slate-500 focus:border-sky-400"
                            placeholder="Entrance"
                          />
                        </label>

                        <label className="block space-y-2 text-sm text-slate-300">
                          <span>Embed FPS</span>
                          <input
                            type="number"
                            min="1"
                            step="1"
                            value={cameraForm.embed_fps}
                            onChange={(event) => setCameraForm((current) => ({ ...current, embed_fps: event.target.value }))}
                            className="w-full rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-white outline-none transition placeholder:text-slate-500 focus:border-sky-400"
                            placeholder="15"
                          />
                        </label>

                        <label className="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-300 md:col-span-2">
                          <input
                            type="checkbox"
                            checked={cameraForm.enabled}
                            onChange={(event) => setCameraForm((current) => ({ ...current, enabled: event.target.checked }))}
                            className="h-4 w-4 rounded border-white/20 bg-slate-900 text-sky-500"
                          />
                          Enable camera immediately after creation
                        </label>
                      </div>

                      <DialogFooter className="gap-3 sm:gap-3">
                        <button
                          type="button"
                          onClick={() => setCameraDialogOpen(false)}
                          className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-200 transition hover:bg-white/10"
                        >
                          Cancel
                        </button>
                        <button
                          type="submit"
                          disabled={creatingCamera}
                          className="rounded-2xl bg-sky-500 px-4 py-3 text-sm font-semibold text-slate-950 transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {creatingCamera ? 'Creating...' : 'Create camera'}
                        </button>
                      </DialogFooter>
                    </form>
                  </DialogContent>
                </Dialog>
              </div>
            </div>

            {cameras.length === 0 ? (
              <div className="mt-6 rounded-[24px] border border-dashed border-white/15 bg-black/20 p-8 text-center text-slate-400">
                <Camera className="mx-auto h-10 w-10 text-slate-500" />
                <p className="mt-3 text-lg font-semibold text-white">No cameras to render</p>
                <p className="mt-2 text-sm">Add cameras from the backend and the registry will populate automatically.</p>
              </div>
            ) : (
              <div className="mt-6 grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
                {cameras.map((camera) => {
                  const detection = detections[camera.id];
                  return (
                    <CameraFeed
                      key={camera.id}
                      id={camera.id}
                      name={camera.name}
                      location={camera.location}
                      streamUrl={camera.streamUrl}
                      enabled={camera.enabled}
                      detectionLabel={detection ? String(detection.label || 'normal').toUpperCase() : undefined}
                      detectionScore={typeof detection?.score === 'number' ? detection.score : null}
                      isAlert={Boolean(detection?.is_alert)}
                    />
                  );
                })}
              </div>
            )}
          </div>
        </section>
      );
    }

    if (activeTab === 'alerts') {
      return (
        <section className="mt-6 grid gap-5 xl:grid-cols-[1fr_320px]">
          <div className="rounded-[28px] border border-white/10 bg-slate-950/70 p-6 shadow-[0_24px_60px_rgba(2,6,23,0.35)]">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Alert center</p>
                <h3 className="mt-1 text-2xl font-semibold">Live event feed</h3>
              </div>
              <ShieldAlert className="h-5 w-5 text-rose-400" />
            </div>
            <div className="mt-5">
              <AlertPanel alerts={alerts} onDismiss={(id) => setAlerts((items) => items.filter((item) => item.id !== id))} />
            </div>
          </div>

          <div className="space-y-4">
            <div className="rounded-[28px] border border-white/10 bg-slate-950/70 p-5 shadow-[0_24px_60px_rgba(2,6,23,0.35)]">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Alert summary</p>
              <div className="mt-4 space-y-3 text-sm text-slate-300">
                <div className="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                  <span>Warnings</span>
                  <span className="font-semibold text-white">{alertCount}</span>
                </div>
                <div className="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                  <span>Info items</span>
                  <span className="font-semibold text-white">{alerts.length - alertCount}</span>
                </div>
                <div className="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                  <span>Last update</span>
                  <span className="font-semibold text-white">{lastUpdated || 'pending'}</span>
                </div>
              </div>
            </div>

            <div className="rounded-[28px] border border-white/10 bg-slate-950/70 p-5 shadow-[0_24px_60px_rgba(2,6,23,0.35)]">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Alert status</p>
              <h4 className="mt-2 text-lg font-semibold text-white">What the sidebar shows on click</h4>
              <p className="mt-2 text-sm text-slate-400">
                This section now reacts to the Alerts tab with a dedicated feed and summary instead of the generic dashboard cards.
              </p>
            </div>
          </div>
        </section>
      );
    }

    if (activeTab === 'analytics') {
      return (
        <section className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <div className="rounded-[28px] border border-white/10 bg-slate-950/70 p-6 shadow-[0_24px_60px_rgba(2,6,23,0.35)]">
            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Activity</p>
            <h3 className="mt-2 text-2xl font-semibold">Operational snapshot</h3>
            <div className="mt-5 space-y-4">
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <p className="text-sm text-slate-400">24h events</p>
                <p className="mt-2 text-3xl font-semibold text-white">{metricValue(summary?.events_24h, '0')}</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <p className="text-sm text-slate-400">Critical alerts</p>
                <p className="mt-2 text-3xl font-semibold text-white">{metricValue(summary?.critical_alerts, '0')}</p>
              </div>
            </div>
          </div>

          <div className="rounded-[28px] border border-white/10 bg-slate-950/70 p-6 shadow-[0_24px_60px_rgba(2,6,23,0.35)]">
            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Health</p>
            <h3 className="mt-2 text-2xl font-semibold">Resource usage</h3>
            <div className="mt-5 space-y-4 text-sm text-slate-300">
              <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-4">
                <div className="flex items-center justify-between">
                  <span>CPU</span>
                  <span className="font-semibold text-white">{cpuValue}%</span>
                </div>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-4">
                <div className="flex items-center justify-between">
                  <span>RAM</span>
                  <span className="font-semibold text-white">{ramValue}%</span>
                </div>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-4">
                <div className="flex items-center justify-between">
                  <span>Disk</span>
                  <span className="font-semibold text-white">{diskValue}%</span>
                </div>
              </div>
            </div>
          </div>

          <div className="rounded-[28px] border border-white/10 bg-slate-950/70 p-6 shadow-[0_24px_60px_rgba(2,6,23,0.35)] md:col-span-2 xl:col-span-1">
            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Coverage</p>
            <h3 className="mt-2 text-2xl font-semibold">System distribution</h3>
            <div className="mt-5 space-y-3">
              <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-4">
                <div className="flex items-center justify-between text-sm text-slate-300">
                  <span>Active cameras</span>
                  <span className="font-semibold text-white">{onlineCameras}</span>
                </div>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-4">
                <div className="flex items-center justify-between text-sm text-slate-300">
                  <span>Total cameras</span>
                  <span className="font-semibold text-white">{cameras.length}</span>
                </div>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-4">
                <div className="flex items-center justify-between text-sm text-slate-300">
                  <span>Storage</span>
                  <span className="font-semibold text-white">{storageValue}</span>
                </div>
              </div>
            </div>
          </div>
        </section>
      );
    }

    if (activeTab === 'layout') {
      return (
        <section className="mt-6 grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
          <div className="rounded-[28px] border border-white/10 bg-slate-950/70 p-6 shadow-[0_24px_60px_rgba(2,6,23,0.35)]">
            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Layout editor</p>
            <h3 className="mt-2 text-2xl font-semibold">Screen arrangement</h3>
            <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {['Grid view', 'Single focus', 'Alert wall', 'Mobile stack', 'Operator view', 'Admin view'].map((item, index) => (
                <div key={item} className="rounded-3xl border border-white/10 bg-white/5 p-4">
                  <div className="flex items-center justify-between text-xs uppercase tracking-[0.22em] text-slate-500">
                    <span>Preset {index + 1}</span>
                    <span className={index === 0 ? 'text-emerald-400' : 'text-slate-400'}>{index === 0 ? 'Active' : 'Available'}</span>
                  </div>
                  <div className="mt-4 h-28 rounded-2xl border border-dashed border-white/15 bg-slate-900/70 p-3">
                    <div className="grid h-full grid-cols-3 gap-2">
                      <div className="rounded-lg bg-sky-500/20" />
                      <div className="rounded-lg bg-white/10" />
                      <div className="rounded-lg bg-white/10" />
                      <div className="col-span-2 rounded-lg bg-white/10" />
                      <div className="rounded-lg bg-emerald-500/20" />
                    </div>
                  </div>
                  <p className="mt-3 text-sm text-slate-300">{item}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="space-y-4">
            <div className="rounded-[28px] border border-white/10 bg-slate-950/70 p-6 shadow-[0_24px_60px_rgba(2,6,23,0.35)]">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Quick controls</p>
              <div className="mt-4 space-y-3">
                <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-300">Drag feeds to prioritize critical zones.</div>
                <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-300">Pin a camera to keep it in focus.</div>
                <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-300">Switch between grid and single view presets.</div>
              </div>
            </div>

            <div className="rounded-[28px] border border-white/10 bg-slate-950/70 p-6 shadow-[0_24px_60px_rgba(2,6,23,0.35)]">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Visual search state</p>
              <h4 className="mt-2 text-lg font-semibold text-white">Sidebar click behavior</h4>
              <p className="mt-2 text-sm text-slate-400">
                The visual search tab now has its own panel instead of reusing the camera grid.
              </p>
            </div>
          </div>
        </section>
      );
    }

    if (activeTab === 'settings') {
      return (
        <section className="mt-6 grid gap-5 xl:grid-cols-[1fr_340px]">
          <div className="rounded-[28px] border border-white/10 bg-slate-950/70 p-6 shadow-[0_24px_60px_rgba(2,6,23,0.35)]">
            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Backend configuration</p>
            <h3 className="mt-2 text-2xl font-semibold">System settings</h3>
            
            {dataError && activeTab === 'settings' && (
              <div className="mt-4 rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                {dataError}
              </div>
            )}

            <form onSubmit={handleSaveSettings} className="mt-6 space-y-4">
              <div className="space-y-4">
                {settings && settings.length > 0 ? (
                  settings.map((setting) => (
                    <div key={setting.key} className="rounded-3xl border border-white/10 bg-white/5 p-5">
                      <div className="flex flex-col gap-2">
                        <label className="text-xs uppercase tracking-[0.22em] text-slate-500">
                          {setting.key.replace(/_/g, ' ')}
                        </label>
                        {setting.description && (
                          <p className="text-xs text-slate-400">{setting.description}</p>
                        )}
                        <input
                          type={/^[0-9]+$/.test(settingsEditing[setting.key] || '') ? 'number' : 'text'}
                          value={settingsEditing[setting.key] || ''}
                          onChange={(event) =>
                            setSettingsEditing((current) => ({
                              ...current,
                              [setting.key]: event.target.value,
                            }))
                          }
                          className="mt-2 rounded-2xl border border-white/10 bg-slate-900/50 px-3 py-2 text-white outline-none transition placeholder:text-slate-500 focus:border-sky-400"
                        />
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-3xl border border-white/10 bg-white/5 p-5 text-slate-400">
                    Loading settings...
                  </div>
                )}
              </div>

              <button
                type="submit"
                disabled={settingsSaving}
                className="mt-6 w-full rounded-2xl bg-sky-500 px-4 py-3 font-semibold text-slate-950 transition hover:bg-sky-400 disabled:opacity-50"
              >
                {settingsSaving ? 'Saving...' : 'Save Changes'}
              </button>
            </form>
          </div>

          <div className="space-y-4">
            <div className="rounded-[28px] border border-white/10 bg-slate-950/70 p-5 shadow-[0_24px_60px_rgba(2,6,23,0.35)]">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">System Info</p>
              <div className="mt-4 space-y-3 text-sm text-slate-300">
                <div className="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                  <span>Role</span>
                  <span className="font-semibold text-white">{role || 'unknown'}</span>
                </div>
                <div className="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                  <span>Cameras</span>
                  <span className="font-semibold text-white">{cameras.length}</span>
                </div>
                <div className="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                  <span>Alerts</span>
                  <span className="font-semibold text-white">{alertCount}</span>
                </div>
              </div>
            </div>

            <div className="rounded-[28px] border border-white/10 bg-slate-950/70 p-5 shadow-[0_24px_60px_rgba(2,6,23,0.35)]">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">About</p>
              <h4 className="mt-2 text-lg font-semibold text-white">SURVEILX</h4>
              <p className="mt-2 text-sm text-slate-400">
                Modify backend configuration settings from this panel.
              </p>
            </div>
          </div>
        </section>
      );
    }

    return (
      <>
        <header className="flex flex-col gap-4 rounded-[28px] border border-white/10 bg-slate-950/70 px-6 py-5 shadow-[0_24px_60px_rgba(2,6,23,0.35)] backdrop-blur md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">{role === 'admin' ? 'Admin dashboard' : 'Operator dashboard'}</p>
            <h2 className="mt-1 text-2xl font-semibold text-white">Live surveillance overview</h2>
            <p className="mt-2 text-sm text-slate-400">
              Rendering backend cameras, detections, and system health from your own project.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
              <p className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Cameras</p>
              <p className="mt-2 text-xl font-semibold">{cameras.length}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
              <p className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Online</p>
              <p className="mt-2 text-xl font-semibold">{onlineCameras}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
              <p className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Alerts</p>
              <p className="mt-2 text-xl font-semibold">{alertCount}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
              <p className="text-[11px] uppercase tracking-[0.24em] text-slate-500">Disk</p>
              <p className="mt-2 text-xl font-semibold">{diskValue}%</p>
            </div>
          </div>
        </header>

        <section className="mt-6 grid gap-4 md:grid-cols-3">
          <div className="rounded-[28px] border border-white/10 bg-slate-950/70 p-5 shadow-[0_24px_60px_rgba(2,6,23,0.35)]">
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.24em] text-slate-500">
              <Cpu className="h-4 w-4 text-sky-400" /> CPU
            </div>
            <p className="mt-4 text-3xl font-semibold">{cpuValue}%</p>
            <p className="mt-2 text-sm text-slate-400">Current host utilisation</p>
          </div>
          <div className="rounded-[28px] border border-white/10 bg-slate-950/70 p-5 shadow-[0_24px_60px_rgba(2,6,23,0.35)]">
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.24em] text-slate-500">
              <Activity className="h-4 w-4 text-emerald-400" /> RAM
            </div>
            <p className="mt-4 text-3xl font-semibold">{ramValue}%</p>
            <p className="mt-2 text-sm text-slate-400">Backend memory usage</p>
          </div>
          <div className="rounded-[28px] border border-white/10 bg-slate-950/70 p-5 shadow-[0_24px_60px_rgba(2,6,23,0.35)]">
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.24em] text-slate-500">
              <HardDrive className="h-4 w-4 text-amber-400" /> Summary
            </div>
            <p className="mt-4 text-3xl font-semibold">{metricValue(summary?.events_24h, '0')}</p>
            <p className="mt-2 text-sm text-slate-400">Events captured in the last 24 hours</p>
          </div>
        </section>

        <section className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="space-y-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Live cameras</p>
                <h3 className="mt-1 text-xl font-semibold">Backend-driven stream registry</h3>
              </div>
              <div className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs uppercase tracking-[0.22em] text-slate-400">
                {loadingData ? 'Syncing' : 'Synced'}
              </div>
            </div>

            {cameras.length === 0 ? (
              <div className="rounded-[28px] border border-dashed border-white/15 bg-slate-950/60 p-10 text-center text-slate-400">
                <Camera className="mx-auto h-12 w-12 text-slate-500" />
                <h4 className="mt-4 text-lg font-semibold text-white">No cameras configured yet</h4>
                <p className="mx-auto mt-2 max-w-xl text-sm leading-6">
                  Your backend currently returns no enabled cameras. Add camera records through the admin side of the project,
                  and this dashboard will automatically render the live streams here.
                </p>
              </div>
            ) : (
              <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
                {cameras.map((camera) => {
                  const detection = detections[camera.id];
                  const alertLabel = detection ? String(detection.label || 'normal').toUpperCase() : undefined;
                  return (
                    <CameraFeed
                      key={camera.id}
                      id={camera.id}
                      name={camera.name}
                      location={camera.location}
                      streamUrl={camera.streamUrl}
                      enabled={camera.enabled}
                      detectionLabel={alertLabel}
                      detectionScore={typeof detection?.score === 'number' ? detection.score : null}
                      isAlert={Boolean(detection?.is_alert)}
                    />
                  );
                })}
              </div>
            )}
          </div>

          <div className="space-y-5">
            <div className="rounded-[28px] border border-white/10 bg-slate-950/70 p-5 shadow-[0_24px_60px_rgba(2,6,23,0.35)]">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Detection feed</p>
                  <h3 className="mt-1 text-xl font-semibold">Latest backend events</h3>
                </div>
                <ShieldAlert className="h-5 w-5 text-rose-400" />
              </div>
              <div className="mt-4">
                <AlertPanel alerts={alerts} onDismiss={(id) => setAlerts((items) => items.filter((item) => item.id !== id))} />
              </div>
            </div>

            <div className="rounded-[28px] border border-white/10 bg-slate-950/70 p-5 shadow-[0_24px_60px_rgba(2,6,23,0.35)]">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs uppercase tracking-[0.3em] text-slate-500">System summary</p>
                  <h3 className="mt-1 text-xl font-semibold">Backend snapshot</h3>
                </div>
                <Sparkles className="h-5 w-5 text-sky-400" />
              </div>

              <div className="mt-4 space-y-3 text-sm text-slate-300">
                <div className="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                  <span>Total streams</span>
                  <span className="font-medium text-white">{metricValue(summary?.streams, '0')}</span>
                </div>
                <div className="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                  <span>Active users</span>
                  <span className="font-medium text-white">{metricValue(summary?.active_users, '0')}</span>
                </div>
                <div className="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                  <span>Critical alerts</span>
                  <span className="font-medium text-white">{metricValue(summary?.critical_alerts, '0')}</span>
                </div>
                <div className="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                  <span>Last updated</span>
                  <span className="font-medium text-white">{lastUpdated || 'pending'}</span>
                </div>
              </div>
            </div>
          </div>
        </section>
      </>
    );
  };

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(14,165,233,0.18),_transparent_32%),linear-gradient(180deg,_#020617_0%,_#050816_45%,_#020617_100%)] text-white">
      {!isAuthenticated ? (
        <div className="flex min-h-screen items-center justify-center px-4 py-10">
          <div className="grid w-full max-w-5xl gap-0 overflow-hidden rounded-[32px] border border-white/10 bg-slate-950/85 shadow-[0_30px_120px_rgba(2,6,23,0.6)] lg:grid-cols-[1.15fr_0.85fr]">
            <div className="relative overflow-hidden p-8 lg:p-12">
              <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,_rgba(14,165,233,0.18),_transparent_28%),radial-gradient(circle_at_bottom_left,_rgba(244,63,94,0.15),_transparent_30%)]" />
              <div className="relative space-y-6">
                <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs uppercase tracking-[0.3em] text-slate-300">
                  <ShieldAlert className="h-4 w-4 text-sky-400" />
                  SURVEILX Operations Center
                </div>
                <div className="space-y-4">
                  <h1 className="max-w-xl text-4xl font-semibold leading-tight sm:text-5xl">
                    Real surveillance data, not a design template.
                  </h1>
                  <p className="max-w-2xl text-sm leading-6 text-slate-300 sm:text-base">
                    Sign in to view live camera streams, detection snapshots, and system health from your FastAPI backend.
                    The dashboard renders whatever the backend currently has configured, including empty states when no cameras exist yet.
                  </p>
                </div>

                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                    <div className="flex items-center gap-2 text-xs uppercase tracking-[0.24em] text-slate-400">
                      <Camera className="h-4 w-4 text-sky-400" />
                      Cameras
                    </div>
                    <div className="mt-3 text-2xl font-semibold">{metricValue(onlineCameras, '0')}</div>
                    <p className="mt-1 text-xs text-slate-400">Loaded from backend registry</p>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                    <div className="flex items-center gap-2 text-xs uppercase tracking-[0.24em] text-slate-400">
                      <AlertTriangle className="h-4 w-4 text-amber-400" />
                      Alerts
                    </div>
                    <div className="mt-3 text-2xl font-semibold">{metricValue(alertCount, '0')}</div>
                    <p className="mt-1 text-xs text-slate-400">Derived from live detections</p>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                    <div className="flex items-center gap-2 text-xs uppercase tracking-[0.24em] text-slate-400">
                      <Cpu className="h-4 w-4 text-emerald-400" />
                      Health
                    </div>
                    <div className="mt-3 text-2xl font-semibold">{cpuValue}%</div>
                    <p className="mt-1 text-xs text-slate-400">CPU from system health endpoint</p>
                  </div>
                </div>
              </div>
            </div>

            <form onSubmit={handleLogin} className="space-y-5 border-t border-white/10 bg-slate-950/95 p-8 lg:border-l lg:border-t-0 lg:p-12">
              <div className="space-y-2">
                <h2 className="text-2xl font-semibold">Sign in</h2>
                <p className="text-sm text-slate-400">Use the same credentials configured in your backend database.</p>
              </div>

              <div className="space-y-4">
                <label className="block space-y-2 text-sm text-slate-300">
                  <span>Username</span>
                  <input
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    className="w-full rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-white outline-none transition placeholder:text-slate-500 focus:border-sky-400"
                    placeholder="admin"
                    autoComplete="username"
                  />
                </label>

                <label className="block space-y-2 text-sm text-slate-300">
                  <span>Password</span>
                  <input
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    className="w-full rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-white outline-none transition placeholder:text-slate-500 focus:border-sky-400"
                    placeholder="••••••••"
                    autoComplete="current-password"
                  />
                </label>

                <label className="block space-y-2 text-sm text-slate-300">
                  <span>Role</span>
                  <select
                    value={loginRole}
                    onChange={(event) => setLoginRole(event.target.value as 'user' | 'admin')}
                    className="w-full rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-white outline-none transition focus:border-sky-400"
                  >
                    <option value="user">User</option>
                    <option value="admin">Admin</option>
                  </select>
                </label>
              </div>

              {(authError || dataError) && (
                <div className="rounded-2xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-200">
                  {authError || dataError}
                </div>
              )}

              <button
                type="submit"
                disabled={authLoading}
                className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-sky-500 px-4 py-3 text-sm font-semibold text-slate-950 transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {authLoading ? <Sparkles className="h-4 w-4 animate-pulse" /> : <User className="h-4 w-4" />}
                Enter dashboard
              </button>

              <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-xs leading-5 text-slate-400">
                If your backend still has no cameras configured, the dashboard will load an empty registry instead of showing demo content.
              </div>
            </form>
          </div>
        </div>
      ) : (
        <div className="flex min-h-screen flex-col xl:flex-row">
          <aside className="border-b border-white/10 bg-slate-950/70 backdrop-blur xl:min-h-screen xl:w-80 xl:border-b-0 xl:border-r">
            <Sidebar
              activeTab={activeTab}
              onTabChange={setActiveTab}
              cameraCount={cameras.length}
              activeCameraCount={onlineCameras}
              alertCount={alertCount}
              storageValue={storageValue}
              role={role}
              lastUpdated={lastUpdated}
            />

            <div className="border-t border-white/10 px-6 py-4">
              <button
                type="button"
                onClick={() => void refreshData()}
                className="inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-200 transition hover:bg-white/10"
              >
                <RefreshCw className={`h-4 w-4 ${loadingData ? 'animate-spin' : ''}`} />
                Refresh live data
              </button>

              <button
                type="button"
                onClick={() => void logout()}
                className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-white/10 bg-transparent px-4 py-3 text-sm text-slate-300 transition hover:bg-white/5"
              >
                <LogOut className="h-4 w-4" />
                Sign out
              </button>
            </div>
          </aside>

          <main className="flex-1 px-5 py-6 sm:px-6 lg:px-8">
            {renderTabContent()}
          </main>
        </div>
      )}
    </div>
  );
}