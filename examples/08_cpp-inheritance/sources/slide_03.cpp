#include <iostream>
#include <string>
#include <cassert>
struct A {
  int id;
  explicit A(int n) : id(n) {
    std::cout << "A(" << id << ") ";
  }
};
struct B : A {
  B() : A(1) { std::cout << "B "; }
};
struct C : A {
  C() : A(2) { std::cout << "C "; }
};
struct D : B, C {
  D() { std::cout << "D\n"; }
};
int main() {
D d; assert(d.B::id == 1); assert(d.C::id == 2);
}
