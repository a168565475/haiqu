import { localStg } from '@/utils/storage';

/** Clear auth storage */
export function clearAuthStorage() {
  localStg.remove('token');
  localStg.remove('refreshToken');
}
