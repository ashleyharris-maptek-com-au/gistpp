
GistPP formalises the next level of the software development tech stack:

![Tech Stack](techStack.jpg)

Combing the rapid development capabilities of LLMs and vibe coding, with the structure and safety of established
software development practices, such as tests, formalised interfaces.

# Getting Started

TODO

# Why?

How often do you, as a software engineer, find yourself reading or writing assembly code? Rarely, right? You've 
got a competent compiler that allows you to use a higher-level language to hide the details of assembly code from you.

I hypothesise that state-of-the-art LLMs are now able to do this for high-level languages, such as C++, Rust, C#, and this
project is an attempt to prove that. 

GistPP allows you to write code in a very-high-level language, annotated markdown with a high-level description of the code, yet
still maintain the same structure and safety of established software development practices, such as segmenting functionality,
writing unit tests, formalised interfaces, integration tests, etc.

# What

Compiler development is complex, as compilers should be written in the language they compile. For the first version of GistPP, 
we use python to bootstrap v1 of the compiler, allowing the compiler to eventually compile itself.

