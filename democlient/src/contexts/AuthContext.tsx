import React, { createContext, useContext, useEffect, ReactNode } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { getCurrentUser, UserInfo, clearUserInfo } from '../services/backendAuthService';
import { RootState } from '../store/store';
import { setUser, clearUser, setLoading, setError } from '../store/slices/authSlice';
import { fetchAvailableAgents } from '../store/slices/agentSlice';
import { AppDispatch } from '../store/store';

interface AuthContextType {
  isLoggedIn: boolean;
  user: UserInfo | null;
  loading: boolean;
  error: string | null;
  checkAuth: () => Promise<void>;
  logout: () => void;
}

// Create a context with default values
const AuthContext = createContext<AuthContextType>({
  isLoggedIn: false,
  user: null,
  loading: true,
  error: null,
  checkAuth: async () => {},
  logout: () => {},
});

export const useAuth = () => useContext(AuthContext);

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const dispatch = useDispatch<AppDispatch>();
  
  // Get auth state from Redux
  const {
    user,
    isAuthenticated: isLoggedIn,
    loading,
    error
  } = useSelector((state: RootState) => state.auth);

  const checkAuth = async () => {
    dispatch(setLoading(true));
    try {
      // Get user info from backend
      const userInfo = await getCurrentUser();
      
      if (userInfo && userInfo.id) {
        // Update Redux state
        dispatch(setUser(userInfo));
        
        // After successful authentication, fetch available agents
        dispatch(fetchAvailableAgents());
      } else {
        dispatch(clearUser());
      }
    } catch (err) {
      dispatch(setError(err instanceof Error ? err.message : 'Failed to authenticate user'));
    } finally {
      dispatch(setLoading(false));
    }
  };

  const logout = () => {
    clearUserInfo();
    dispatch(clearUser());
    
    // For App Service Auth, redirect to the logout URL
    window.location.href = '/.auth/logout';
  };

  useEffect(() => {
    checkAuth();
  }, []);

  // Provide the values from Redux state
  const authContextValue: AuthContextType = {
    isLoggedIn,
    user,
    loading,
    error,
    checkAuth,
    logout
  };

  return (
    <AuthContext.Provider value={authContextValue}>
      {children}
    </AuthContext.Provider>
  );
}; 