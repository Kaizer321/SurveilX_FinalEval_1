import { create } from 'zustand';
import apiClient from './api';

interface AuthState {
  token: string | null;
  role: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  
  login: (username: string, password: string, role?: string) => Promise<void>;
  logout: () => Promise<void>;
  checkAuth: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem('auth_token'),
  role: localStorage.getItem('user_role'),
  isAuthenticated: !!localStorage.getItem('auth_token'),
  isLoading: false,
  error: null,

  login: async (username: string, password: string, role?: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await apiClient.login({ username, password, role });
      localStorage.setItem('user_role', response.role);
      set({
        token: response.token,
        role: response.role,
        isAuthenticated: true,
        isLoading: false,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Login failed';
      set({ error: message, isLoading: false });
      throw error;
    }
  },

  logout: async () => {
    set({ isLoading: true });
    try {
      await apiClient.logout();
      localStorage.removeItem('user_role');
      set({
        token: null,
        role: null,
        isAuthenticated: false,
        isLoading: false,
      });
    } catch (error) {
      console.error('Logout error:', error);
      set({ isLoading: false });
    }
  },

  checkAuth: async () => {
    const token = apiClient.getToken();
    if (!token) {
      set({ isAuthenticated: false });
      return;
    }

    try {
      const user = await apiClient.getCurrentUser();
      set({
        isAuthenticated: true,
        role: user.role,
      });
    } catch (error) {
      apiClient.setToken(null);
      localStorage.removeItem('user_role');
      set({ isAuthenticated: false, role: null });
    }
  },
}));
