# Anti-Patterns

## Fat Route Modules

Symptoms include forms, feature state, schemas, database imports, or business rules in
`src/routes`. Keep paths and route lifecycle behavior there; move the feature behavior
to its owning slice.

## Route Guards As Security

A redirect protects navigation UX, not data. Every private server function and server
route authorizes using trusted server-derived identity.

## Folder Names As Runtime Protection

A directory called `server` does not prevent browser bundling. Use `*.server.ts`, Start
import protection, and correct imports.

## One Feature Per Page

Features represent business capabilities, not route names. One feature may support
several routes, and one route may compose several features.

## Speculative Shared Code

Do not move a component, hook, type, or utility to `shared` because it might be reused.
Promote it only after ownership is genuinely cross-feature.

## Catch-All Services And Utilities

Avoid global `services/` and unrelated `utils.ts` collections. Use feature server
functions and focused utilities such as `env.server.ts`, `logger.ts`, or `cn.ts`.

## Direct Infrastructure In Loaders

Loaders are isomorphic. They call server functions rather than importing a database,
filesystem, secret environment module, or private SDK.

## Premature Platform Defaults

Do not make a database, auth provider, analytics vendor, query cache, or cloud adapter a
template requirement before the application has that need.
