import { Component, type ReactNode } from 'react'

/** Filet de securite : une erreur de rendu affiche un message et un bouton de rechargement au lieu d'une page blanche. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  render() {
    if (!this.state.error) return this.props.children
    const fr = (document.documentElement.lang || 'fr') === 'fr'
    return (
      <div className="fatal" role="alert">
        <h1>{fr ? 'Une erreur inattendue est survenue.' : 'Something went wrong.'}</h1>
        <p className="muted">{fr ? 'Vos conversations sont enregistrées sur le serveur.' : 'Your conversations are saved on the server.'}</p>
        <button type="button" className="btn btn--primary" onClick={() => window.location.reload()}>
          {fr ? 'Recharger la page' : 'Reload the page'}
        </button>
      </div>
    )
  }
}
