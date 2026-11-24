import { createAlovaRequest } from '@sa/alova';
import adapterFetch from '@sa/alova/fetch';
import { createAlovaMockAdapter } from '@sa/alova/mock';
import { getServiceBaseURL } from '@/utils/service';
import { $t } from '@/locales';
import { localStg } from '@/utils/storage';
import featureUsers20241014 from '../mocks/feature-users-20241014';
import { getAuthorization, handleRefreshToken, showErrorMsg } from './shared';
import type { RequestInstanceState } from './type';

const isHttpProxy = import.meta.env.DEV && import.meta.env.VITE_HTTP_PROXY === 'Y';
const { baseURL } = getServiceBaseURL(import.meta.env, isHttpProxy);

const state: RequestInstanceState = {
  errMsgStack: []
};
const mockAdapter = createAlovaMockAdapter([featureUsers20241014], {
  // using requestAdapter if not match mock request
  httpAdapter: adapterFetch(),

  // response delay time
  delay: 1000,

  // global mock toggle
  enable: true,
  matchMode: 'methodurl'
});
export const alova = createAlovaRequest(
  {
    baseURL,
    requestAdapter: import.meta.env.DEV ? mockAdapter : adapterFetch()
  },
  {
    onRequest({ config }) {
      const Authorization = getAuthorization();
      config.headers.Authorization = Authorization;
      config.headers.apifoxToken = 'XL299LiMEDZ0H5h3A29PxwQXdMJqWyY2';
    },
    tokenRefresher: {
      async isExpired(response) {
        if (!localStg.get('refreshToken')) return false;

        const expiredTokenCodes = import.meta.env.VITE_SERVICE_EXPIRED_TOKEN_CODES?.split(',') || [];
        const { code } = await response.clone().json();
        return expiredTokenCodes.includes(String(code));
      },
      async handler() {
        await handleRefreshToken();
      }
    },
    async isBackendSuccess(response) {
      // when the backend response code is "0000"(default), it means the request is success
      // to change this logic by yourself, you can modify the `VITE_SERVICE_SUCCESS_CODE` in `.env` file
      const resp = response.clone();
      const data = await resp.json();
      return String(data.code) === import.meta.env.VITE_SERVICE_SUCCESS_CODE;
    },
    async transformBackendResponse(response) {
      return (await response.clone().json()).data;
    },
    async onError(error, response) {
      let message = error.message;
      let responseCode = '';
      if (response) {
        const data = await response?.clone().json();
        message = data.msg;
        responseCode = String(data.code);
      }

      function clearModalError() {
        state.errMsgStack = state.errMsgStack.filter(msg => msg !== message);
      }

      // 演示服务的登录错误只提示，不改变 ERP Session 登录状态。
      const logoutCodes = import.meta.env.VITE_SERVICE_LOGOUT_CODES?.split(',') || [];
      if (logoutCodes.includes(responseCode)) {
        showErrorMsg(state, message);
        throw error;
      }

      // 保留演示错误弹窗，确认或关闭只清理提示记录。
      const modalLogoutCodes = import.meta.env.VITE_SERVICE_MODAL_LOGOUT_CODES?.split(',') || [];
      if (modalLogoutCodes.includes(responseCode) && !state.errMsgStack?.includes(message)) {
        state.errMsgStack = [...(state.errMsgStack || []), message];

        window.$dialog?.error({
          title: $t('common.error'),
          content: message,
          positiveText: $t('common.confirm'),
          maskClosable: false,
          closeOnEsc: false,
          onPositiveClick() {
            clearModalError();
          },
          onClose() {
            clearModalError();
          }
        });
        throw error;
      }
      showErrorMsg(state, message);
      throw error;
    }
  }
);
