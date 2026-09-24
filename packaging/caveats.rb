# Drop this method into the Formula class in your tap
# (zepuff/homebrew-chronify/Formula/chronify.rb), replacing the current
# `def caveats`. Homebrew prints it right after `brew install chronify`.
#
# The colours turn themselves off when the output is not a terminal, so piping
# `brew install` into a file or a CI log stays clean.

  def caveats
    tty = $stdout.tty?
    b   = tty ? "\e[1m"    : ""   # bold
    h   = tty ? "\e[1;36m" : ""   # bold cyan, for headings
    g   = tty ? "\e[1;32m" : ""   # bold green, for things to type
    d   = tty ? "\e[2m"    : ""   # dim, for asides
    r   = tty ? "\e[0m"    : ""   # reset

    <<~EOS
      #{b}Chronify is the ⏱ clock that now lives in your menu bar.#{r}
      It watches which window is in front and writes your workday down for you:
      hours per task, a daily status built from your own rough notes, and the
      numbers your timesheet and invoice need at the end of the month.
      #{d}Everything stays on this Mac. No account, no cloud, no API key.#{r}

      #{d}Made for people who bill by the hour: contractors, freelancers, anyone
      who has to say what they did today and how long it took.#{r}

      #{h}START HERE — three steps, about two minutes#{r}
        #{g}1.#{r} #{g}chronify --background#{r}
           Starts it and gives this terminal back. Plain `chronify` runs it
           here instead, where Ctrl+C quits it.

        #{g}2.#{r} #{b}Allow Screen Recording#{r} when macOS asks
           Without it window titles are invisible and your whole day is logged
           as bare app names with no task breakdown. Quit and start Chronify
           again afterwards, macOS only reads that permission at launch.

        #{g}3.#{r} #{b}⏱ → 🏷 Project → + Add a project#{r}
           Every hour belongs to a project, so nothing is recorded until one
           exists. Only the name is required.

      #{h}THEN, EVERY DAY#{r}
        during the day   #{b}⏱ → ✅ What I did today#{r}
                         #{d}one line per finished thing, written however it comes out#{r}
        in the evening   #{b}⏱ → ✨ Write today's status#{r}
                         #{d}turns those lines into text you can paste into Slack#{r}
        end of month     #{b}⏱ → 🧾 Invoice#{r} and #{b}📤 Send hours to PeopleForce#{r}

      #{d}Every item in the menu carries a small grey line explaining what it
      does, so you can read the menu instead of the manual.#{r}

      #{h}OPTIONAL#{r}
        #{g}brew services start chronify#{r}        start it at every login
        #{g}brew install --cask libreoffice#{r}     PDF export for invoices
        A local model that rewrites your notes: #{b}⚙️ Settings → Daily status#{r}
        #{d}picks it and installs it for you, nothing to do by hand.#{r}

      #{h}WHERE THINGS LIVE#{r}
        #{b}~/.work_tracker/#{r}  settings, database, statuses. The one folder to
        back up. config.yaml is created there on the first run and upgrades
        never touch it.

      #{h}THE GUIDE#{r}
        #{b}https://zepuff.github.io/chronify/#{r}
    EOS
  end
