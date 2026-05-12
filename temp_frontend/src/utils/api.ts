// API Configuration and utilities for communicating with the FastAPI backend

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

interface LoginCredentials {
  username: string;
  password: string;
  role?: string;
}

interface LoginResponse {
  token: string;
  role: string;
}

class APIClient {
  private baseURL: string;
  private token: string | null = null;

  constructor(baseURL: string = API_BASE_URL) {
    this.baseURL = baseURL;
    this.token = localStorage.getItem('auth_token');
  }

  /**
   * Set authentication token
   */
  setToken(token: string | null) {
    this.token = token;
    if (token) {
      localStorage.setItem('auth_token', token);
    } else {
      localStorage.removeItem('auth_token');
    }
  }

  /**
   * Get authentication token
   */
  getToken(): string | null {
    return this.token || localStorage.getItem('auth_token');
  }

  /**
   * Make an authenticated request to the API
   */
  async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseURL}${endpoint}`;
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
      ...options.headers,
    };

    // Add authorization token if available
    const token = this.getToken();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(url, {
      ...options,
      headers,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }

    return response.json();
  }

  /**
   * Login with username and password
   */
  async login(credentials: LoginCredentials): Promise<LoginResponse> {
    const response = await this.request<LoginResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(credentials),
    });
    if (response.token) {
      this.setToken(response.token);
    }
    return response;
  }

  /**
   * Logout
   */
  async logout(): Promise<void> {
    try {
      await this.request('/auth/logout', {
        method: 'POST',
      });
    } catch (error) {
      console.error('Logout error:', error);
    }
    this.setToken(null);
  }

  /**
   * Get current user info
   */
  async getCurrentUser(): Promise<any> {
    return this.request('/auth/me');
  }

  /**
   * Get list of cameras
   */
  async getCameras(): Promise<any[]> {
    const response = await this.request<{ cameras?: any[] } | any[]>('/cameras');
    return Array.isArray(response) ? response : response.cameras ?? [];
  }

  /**
   * Get the admin camera registry with source and zone details.
   */
  async getAdminCameras(): Promise<any[]> {
    const response = await this.request<{ cameras?: any[] } | any[]>('/admin/cameras');
    return Array.isArray(response) ? response : response.cameras ?? [];
  }

  /**
   * Create a new admin camera.
   */
  async createCamera(payload: {
    name: string;
    source_url: string;
    zone?: string;
    enabled?: boolean;
    embed_fps?: number;
  }): Promise<any> {
    return this.request('/admin/cameras', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  /**
   * Get camera by ID
   */
  async getCamera(cameraId: string): Promise<any> {
    return this.request(`/cameras/${cameraId}`);
  }

  /**
   * Get camera feed
   */
  async getCameraFeed(cameraId: string): Promise<Blob> {
    const token = this.getToken();
    const headers: HeadersInit = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    
    const response = await fetch(`${this.baseURL}/cameras/${cameraId}/feed`, {
      headers,
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch camera feed: ${response.statusText}`);
    }

    return response.blob();
  }

  /**
   * Get alerts
   */
  async getAlerts(limit: number = 50): Promise<any[]> {
    return this.request(`/alerts?limit=${limit}`);
  }

  /**
   * Get alert by ID
   */
  async getAlert(alertId: string): Promise<any> {
    return this.request(`/alerts/${alertId}`);
  }

  /**
   * Dismiss an alert
   */
  async dismissAlert(alertId: string): Promise<void> {
    await this.request(`/alerts/${alertId}/dismiss`, {
      method: 'POST',
    });
  }

  /**
   * Get analytics/statistics
   */
  async getAnalytics(timeRange: string = '24h'): Promise<any> {
    return this.request(`/analytics?range=${timeRange}`);
  }

  /**
   * Get system status
   */
  async getSystemStatus(): Promise<any> {
    return this.request('/status');
  }

  /**
   * Get the latest detection snapshot for each camera.
   */
  async getLiveDetections(): Promise<Record<string, any>> {
    const response = await this.request<{ detections?: Record<string, any> } | Record<string, any>>('/api/detections');
    if (response && typeof response === 'object' && !Array.isArray(response) && 'detections' in response) {
      return response.detections ?? {};
    }
    return (response as Record<string, any>) ?? {};
  }

  /**
   * Get analytics summary if the current session is admin.
   */
  async getAnalyticsSummary(): Promise<any | null> {
    try {
      return await this.request('/admin/analytics/summary');
    } catch (error) {
      return null;
    }
  }

  /**
   * Get system health stats from the backend.
   */
  async getHealthStats(): Promise<any | null> {
    try {
      return await this.request('/api/stats/health');
    } catch (error) {
      try {
        return await this.request('/admin/health');
      } catch (fallbackError) {
        return null;
      }
    }
  }

  /**
   * Stream alerts using EventSource
   */
  streamAlerts(callback: (alert: any) => void): EventSource {
    const token = this.getToken();
    const url = `${this.baseURL}/alerts/stream${token ? `?token=${token}` : ''}`;
    
    const eventSource = new EventSource(url);
    eventSource.onmessage = (event) => {
      try {
        const alert = JSON.parse(event.data);
        callback(alert);
      } catch (error) {
        console.error('Error parsing alert:', error);
      }
    };

    return eventSource;
  }

  /**
   * Get all backend settings
   */
  async getSettings(): Promise<any> {
    try {
      return await this.request('/api/admin/settings');
    } catch (error) {
      console.error('Error fetching settings:', error);
      return { settings: [] };
    }
  }

  /**
   * Update backend settings
   */
  async updateSettings(payload: Record<string, string>): Promise<any> {
    return this.request('/api/admin/settings', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }
}

export const apiClient = new APIClient();
export default apiClient;
