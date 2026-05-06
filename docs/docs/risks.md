# Risks

This is where I'm collecting my thoughts on what the main weaknesses of the hardware design are.

**1)** I'm assuming that EW remappings happen rarely.  If that's a false assumption it will destroy
performance.  It's something that I should check better.

**2)** Memory accesses can easily become sequential due to waiting for possible address conflicts or
page faults to resolve. We can use custom instructions to get around much of this but then we need
to work out how to get the compiler to emit them, or we need to add them as inline assembly.

**3)** I did some earlier experiments to get the area estimates of the Transfer System in the
jamlet and it gave some fairly low numbers. I'm a little sceptical and need to redo these
measurements with RTL that is tested and working.

**4)** The minimum latency for small transfers between neighboring jamlets is likely fairly high due
to having to traverse the Transfer System.  I'm not confident this latency will be hidden well.

**5)** The systolic array design is half-baked. I'm worried it will not be routable, and I also
don't know how practical the data layout is.


There are probably lots more, but these are the ones that currently spring to mind.
