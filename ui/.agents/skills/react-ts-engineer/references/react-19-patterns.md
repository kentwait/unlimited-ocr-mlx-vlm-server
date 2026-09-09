# React 19 Patterns

Load this reference when implementing React 19 Actions, optimistic updates,
non-blocking transitions, or promise reading with Suspense. Choose the API that
matches the state transition; do not add these patterns when ordinary local
state or event handling is sufficient.

## Form Actions with `useActionState`

Use `useActionState` when a form action needs pending state and a structured
result from the action.

```tsx
const initialState: FormState = { error: null, success: false };

const [state, formAction, isPending] = React.useActionState(
  async (previousState: FormState, formData: FormData): Promise<FormState> => {
    const result = await submitForm(formData);
    return result.error
      ? { error: result.error, success: false }
      : { error: null, success: true };
  },
  initialState,
);

return (
  <form action={formAction}>
    <input name="email" />
    <Button type="submit" disabled={isPending}>
      {isPending ? "Submitting..." : "Submit"}
    </Button>
    {state.error && <p className="text-destructive">{state.error}</p>}
  </form>
);
```

## Optimistic Updates with `useOptimistic`

Use `useOptimistic` when the UI should reflect a mutation before the server
confirms it.

```tsx
const [optimisticItems, addOptimistic] = React.useOptimistic(
  items,
  (currentItems, newItem: Item) => [
    ...currentItems,
    { ...newItem, pending: true },
  ],
);
```

## Non-Blocking Updates with `useTransition`

Use a transition for non-urgent updates that may suspend or require expensive
rendering.

```tsx
const [isPending, startTransition] = React.useTransition();

function handleFilter(query: string): void {
  startTransition(() => setFilteredResults(filterItems(query)));
}
```

## Promise Reading with `use`

Read a promise with `use` only below a Suspense boundary and keep rejected
promise handling within an error boundary.

```tsx
function UserProfile({ userPromise }: { userPromise: Promise<User> }) {
  const user = React.use(userPromise);
  return <h1>{user.name}</h1>;
}

<React.Suspense fallback={<Skeleton />}>
  <UserProfile userPromise={fetchUser(id)} />
</React.Suspense>;
```

Pair the Suspense boundary with an error boundary that renders a recoverable
failure state.
