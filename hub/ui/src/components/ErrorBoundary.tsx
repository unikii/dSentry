import { Component, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { dictionaries, getCurrentLocale, translate } from "@/i18n";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (this.state.error) {
      if (this.props.fallback) return this.props.fallback;
      // Class component: resolve strings from the module-level locale.
      const messages = dictionaries[getCurrentLocale()];
      const t = (key: "error.title" | "error.fallback" | "common.retry") =>
        translate(messages, key) ?? translate(dictionaries.en, key) ?? key;
      return (
        <div className="flex flex-col items-center justify-center gap-4 rounded-xl border border-destructive/40 bg-destructive/5 px-6 py-16 text-center">
          <AlertTriangle className="text-destructive size-10" />
          <div>
            <p className="text-lg font-semibold">{t("error.title")}</p>
            <p className="text-muted-foreground mt-1 max-w-md text-sm">
              {this.state.error.message || t("error.fallback")}
            </p>
          </div>
          <Button
            variant="outline"
            onClick={() => this.setState({ error: null })}
          >
            <RefreshCw className="size-4" />
            {t("common.retry")}
          </Button>
        </div>
      );
    }
    return this.props.children;
  }
}
