#include <iolib/io.hpp>

using namespace io;

class hello : public io::contract {
  public:
      using contract::contract;

      /// @abi action 
      void hi( account_name user ) {
         print( "Hello, ", name{user} );
      }
};

IO_ABI( hello, (hi) )
