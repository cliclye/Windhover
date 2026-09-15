import { Component, type ReactNode } from "react"
interface State { error: Error | null; stack: string }
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null, stack: "" }
  static getDerivedStateFromError(error: Error): Partial<State> { return { error } }
  componentDidCatch(error: Error, info: { componentStack?: string }) {
    console.error("[Windhover] render crash:", error, info.componentStack)
    this.setState({ stack: info.componentStack ?? "" })
  }
  render() {
    if (!this.state.error) return this.props.children
    return <div style={{ padding: "2rem", fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif", color: "inherit", background: "transparent", minHeight: "100vh" }}>
      <h2>Windhover UI hit an error</h2>
      <p style={{ color: "#6f6e69" }}>The engine is unaffected. Try refreshing.</p>
      <pre style={{ whiteSpace: "pre-wrap", color: "#c44032" }}>{String(this.state.error)}</pre>
      <button onClick={() => this.setState({ error: null, stack: "" })} style={{ marginTop: "1rem", padding: "0.5rem 1rem", background: "transparent", color: "inherit", border: "1px solid rgba(28,28,25,.16)", borderRadius: 8, cursor: "pointer" }}>Retry</button>
    </div>
  }
}
