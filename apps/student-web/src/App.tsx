import { ApiProvider } from "./api/ApiContext";
import type { ApiClient } from "./api/client";
import { ErrorState, Loading } from "./components/StateViews";
import { AuthProvider, useAuth } from "./session/AuthContext";
import { LoginScreen } from "./session/LoginScreen";
import type { SessionStore } from "./session/sessionStore";
import { StudentShell } from "./shell/StudentShell";

interface Props {
  api: ApiClient;
  store: SessionStore;
}

export function App({ api, store }: Props) {
  return (
    <ApiProvider client={api}>
      <AuthProvider store={store}>
        <Gate />
      </AuthProvider>
    </ApiProvider>
  );
}

function Gate() {
  const { state, logout, retry } = useAuth();
  switch (state.status) {
    case "checking":
      return (
        <div className="fullpage">
          <Loading label="Restoring your session…" />
        </div>
      );
    case "unreachable":
      return (
        <div className="fullpage">
          <ErrorState error={state.error} onRetry={retry} />
        </div>
      );
    case "signedOut":
      return <LoginScreen />;
    case "signedIn":
      return <StudentShell key={state.me.id} me={state.me} onLogout={logout} />;
  }
}
