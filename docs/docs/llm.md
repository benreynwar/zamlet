I enjoy reading about how other people are using (or not using) LLMs for their projects, so thought I'd add a little section to these docs
about how I've been using Claude Code for this project and my impressions so far.

# Things that It's Helped With

- I've found Claude Code really useful for writing bazel files.  I probably wouldn't have spent the time to learn bazel well enough to use
  it myself, and it's been a big improvement over build tools I've used in the past.  I expect the bazel files in this project are a 
  vibe coded mess, but it seems to have been working well.

- Simalarly it's been useful for learning Chisel.  It turns a short steep learning curve into a long shallow one
  which is often what you want.

- It's useful for when I have questions about the RISC-V spec, and I can ask the LLM rather than searching through the spec myself.

- I enjoy using it as a rubber duck for talking things through.  It forces me to plan things out in advance more than I would otherwise.

- It does an adequate job of quickly writing simple python tests.

- It does a great job of quickly finding simple bugs in my RTL code.

# Things that it's Hindered

- The obvious place where it is a detriment is that it prevents me from learning things that I otherwise would have been forced to learn.
  At some point I need to force myself to learn Bazel properly, so I can understand what I'm doing there.

- Often I want to do something that is too difficult for the LLM, but I don't realize that for a while, and I waste a lot of time trying
  to get the LLM to do it, when it would have take a fraction of the time just to do it myself. It's hard to remember that you can't teach
  the LLM anything, and any time spent teaching it will be wasted.

- Because it's really good at quickly making adequate python tests, I end up writing fewer really good tests.

- It's really easy to lose your mental model of the codebase if you're making edits via an LLM.  The codebase can become a big mess
  quickly.

# Places where it's not useful.

- I don't think it's useful for writing docs for humans.  One of the purposes of writing these kind of things is to help me organize my
  thoughts, and using an LLM somewhat defeats that purpose.  Secondly, I don't want to give up my written voice (even if my written 
  voice is pretty crap).

- I'm using it to write Chisel code, but I don't think it's providing much value there.  I need to spend alot of time developing detailed
  plans and reviewing code to get something halfway reasonable.  I don't think the LLM is hindering me, but it's not helping either.

# Current Strategy

I'm not at all confident that my current LLM usage approach is a good one.  I find using an LLM to write code fairly addictive, often
not in a good way.  I'm trying to force myself to spend more time doing stuff manually so that I retain a good mental model of the
codebase and so that I can better notice when the quality starts to fall off.  I have no idea what the right balance is, but it's
fun getting to play with a new technology and think about what is and isn't working.
