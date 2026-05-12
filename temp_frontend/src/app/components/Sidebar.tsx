import { Video, Settings, Bell, Grid3x3, Layout, BarChart3 } from 'lucide-react';

interface SidebarProps {
  activeTab: string;
  onTabChange: (tab: string) => void;
  cameraCount: number;
  activeCameraCount: number;
  alertCount: number;
  storageValue: string;
  role?: string | null;
  lastUpdated?: string;
}

export function Sidebar({
  activeTab,
  onTabChange,
  cameraCount,
  activeCameraCount,
  alertCount,
  storageValue,
  role,
  lastUpdated,
}: SidebarProps) {
  const menuItems = [
    { id: 'grid', icon: Grid3x3, label: 'Grid View' },
    { id: 'cameras', icon: Video, label: 'Cameras' },
    { id: 'alerts', icon: Bell, label: 'Alerts' },
    { id: 'analytics', icon: BarChart3, label: 'Analytics' },
    { id: 'layout', icon: Layout, label: 'Layout' },
    { id: 'settings', icon: Settings, label: 'Settings' },
  ];

  return (
    <div className="w-64 bg-[#0f0f0f] border-r border-[#2a2a2a] min-h-screen flex flex-col">
      {/* Header */}
      <div className="p-4 border-b border-[#2a2a2a]">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-blue-600 flex items-center justify-center">
            <Video className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-sm text-white">SURVEILX</h1>
            <p className="text-xs text-gray-400">Surveillance System</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-3">
        <ul className="space-y-1">
          {menuItems.map((item) => (
            <li key={item.id}>
              <button
                onClick={() => onTabChange(item.id)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${
                  activeTab === item.id
                    ? 'bg-[#2a2a2a] text-white'
                    : 'text-gray-300 hover:bg-[#1a1a1a]'
                }`}
              >
                <item.icon className="w-5 h-5" />
                <span className="text-sm">{item.label}</span>
              </button>
            </li>
          ))}
        </ul>
      </nav>

      {/* Footer Status */}
      <div className="p-4 border-t border-[#2a2a2a]">
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className="text-gray-400">System Status</span>
            <span className="text-green-500">Operational</span>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-gray-400">Active Cameras</span>
            <span className="text-white">{activeCameraCount}/{cameraCount}</span>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-gray-400">Storage</span>
            <span className="text-white">{storageValue} Used</span>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-gray-400">Alerts</span>
            <span className="text-white">{alertCount}</span>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-gray-400">Role</span>
            <span className="text-white">{role || 'unknown'}</span>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-gray-400">Last Sync</span>
            <span className="text-white">{lastUpdated || 'pending'}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
